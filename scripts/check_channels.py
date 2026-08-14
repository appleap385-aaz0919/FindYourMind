#!/usr/bin/env python
"""화이트리스트 채널 건강 점검 → channel_health.json (PLAN.md Phase 1).

taxonomy.yaml auto_alerts 5종을 판정한다.
    1. 채널이 삭제·비공개되면            → channel_dead
    2. 최근 90일 업로드가 없으면          → channel_stale_uploads
    3. blocklist 통과율이 50% 미만이면    → channel_low_pass_rate
    4. last_reviewed_at이 120일을 넘기면  → channel_review_overdue
    5. 화이트리스트가 15개 미만이면       → allowlist_undersized

판정만 하고 Issue는 만들지 않는다. Issue 생성은 워크플로의 일이다
(판정 로직을 GitHub에서 떼어놔야 로컬에서 그대로 검증할 수 있다).

쿼터: channels.list 1 + playlistItems.list N + videos.list ceil(N*10/50) ≈ 25 units.
채널당 search.list(100 units)를 쓰지 않는 이유는 lib/quota.py 상단 참조.

사용 예:
  python scripts/check_channels.py --dry-run
  python scripts/check_channels.py --out dist/channel_health.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import alerts as alert_specs
from lib.alerts import AlertCollector
from lib.allowlist import (
    MIN_ALLOWLIST_SIZE,
    MIN_BLOCKLIST_PASS_RATE,
    NO_UPLOAD_DAYS,
    REVIEW_OVERDUE_DAYS,
    Allowlist,
    AllowlistChannel,
    load_allowlist,
)
from lib.filters import blocklist_text
from lib.normalize import matched_terms
from lib.quota import QuotaBudget, QuotaExceeded
from lib.quota_log import (
    DAILY_CEILING,
    DEFAULT_LOG,
    QuotaBudgetExceeded,
    check as check_daily_quota,
    record as record_quota,
    table as quota_table,
)
from lib.taxonomy import Taxonomy, load_taxonomy
from lib.youtube import Client, DryRunClient, YouTubeClient

logger = logging.getLogger("check_channels")

RECENT_VIDEO_COUNT = 10  # 채널당 점검할 최근 영상 수
DEFAULT_HARD_CAP = 500  # 이 스크립트만의 상한. 일일 예산은 build_videos.py가 대부분 쓴다.

EXIT_OK = 0
EXIT_RETRYABLE = 1
EXIT_QUOTA = 2


@dataclass
class ChannelHealth:
    channel_id: str
    channel_name: str
    alive: bool
    last_upload_at: str | None
    days_since_upload: int | None
    recent_checked: int
    blocklist_pass_rate: float | None
    blocked_titles: list[str]
    last_reviewed_at: str
    days_since_review: int | None
    status: str

    def to_json(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "alive": self.alive,
            "last_upload_at": self.last_upload_at,
            "days_since_upload": self.days_since_upload,
            "recent_checked": self.recent_checked,
            "blocklist_pass_rate": self.blocklist_pass_rate,
            "blocked_titles": self.blocked_titles[:5],
            "last_reviewed_at": self.last_reviewed_at,
            "days_since_review": self.days_since_review,
            "status": self.status,
        }


def check_channel(
    entry: AllowlistChannel,
    channel_item: dict[str, Any] | None,
    client: Client,
    terms: tuple[str, ...],
    today: date,
    now: datetime,
    collector: AlertCollector,
) -> ChannelHealth:
    """채널 1개를 점검한다."""
    days_since_review = entry.days_since_review(today)
    if days_since_review is not None and days_since_review > REVIEW_OVERDUE_DAYS:
        collector.add(
            **alert_specs.channel_review_overdue(
                entry.channel_id, entry.channel_name, days_since_review
            )
        )

    if channel_item is None:
        logger.error("%s (%s) — 접근 불가", entry.channel_name, entry.channel_id)
        collector.add(**alert_specs.channel_dead(entry.channel_id, entry.channel_name))
        return ChannelHealth(
            channel_id=entry.channel_id,
            channel_name=entry.channel_name,
            alive=False,
            last_upload_at=None,
            days_since_upload=None,
            recent_checked=0,
            blocklist_pass_rate=None,
            blocked_titles=[],
            last_reviewed_at=entry.last_reviewed_at,
            days_since_review=days_since_review,
            status="dead",
        )

    uploads = (
        (channel_item.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
    )
    video_ids = client.playlist_items(str(uploads), RECENT_VIDEO_COUNT) if uploads else []
    items = client.videos(video_ids) if video_ids else []

    last_upload_at, days_since_upload = _latest_upload(items, now)
    pass_rate, blocked_titles = _blocklist_pass_rate(items, terms)

    status = _evaluate(
        entry, days_since_upload, pass_rate, len(items), collector
    )
    return ChannelHealth(
        channel_id=entry.channel_id,
        channel_name=entry.channel_name,
        alive=True,
        last_upload_at=last_upload_at,
        days_since_upload=days_since_upload,
        recent_checked=len(items),
        blocklist_pass_rate=pass_rate,
        blocked_titles=blocked_titles,
        last_reviewed_at=entry.last_reviewed_at,
        days_since_review=days_since_review,
        status=status,
    )


def _evaluate(
    entry: AllowlistChannel,
    days_since_upload: int | None,
    pass_rate: float | None,
    checked: int,
    collector: AlertCollector,
) -> str:
    status = "ok"
    if days_since_upload is None or days_since_upload > NO_UPLOAD_DAYS:
        logger.warning(
            "%s (%s) — 최근 업로드 %s",
            entry.channel_name,
            entry.channel_id,
            f"{days_since_upload}일 전" if days_since_upload is not None else "확인 불가",
        )
        collector.add(
            **alert_specs.channel_stale_uploads(
                entry.channel_id, entry.channel_name, days_since_upload
            )
        )
        status = "stale"
    if pass_rate is not None and pass_rate < MIN_BLOCKLIST_PASS_RATE:
        logger.error(
            "%s (%s) — blocklist 통과율 %.0f%% (%d건 검사)",
            entry.channel_name,
            entry.channel_id,
            pass_rate * 100,
            checked,
        )
        collector.add(
            **alert_specs.channel_low_pass_rate(
                entry.channel_id, entry.channel_name, pass_rate, checked
            )
        )
        status = "risky"
    return status


def _latest_upload(
    items: list[dict[str, Any]], now: datetime
) -> tuple[str | None, int | None]:
    published = [
        str((item.get("snippet") or {}).get("publishedAt", ""))
        for item in items
        if (item.get("snippet") or {}).get("publishedAt")
    ]
    if not published:
        return None, None
    latest = max(published)
    try:
        moment = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    except ValueError:
        return latest, None
    return latest, (now - moment.astimezone(timezone.utc)).days


def _blocklist_pass_rate(
    items: list[dict[str, Any]], terms: tuple[str, ...]
) -> tuple[float | None, list[str]]:
    """최근 영상이 blocklist를 통과하는 비율. 채널 성향 변화의 신호다.

    길이·Shorts 필터는 적용하지 않는다. 여기서 재려는 것은 콘텐츠 성향이지
    영상 형식이 아니다.

    매칭 범위(제목만)는 배치와 동일해야 한다. 여기가 더 넓으면, 배치는 멀쩡히
    통과시키는 채널을 이 점검만 통과율 미달로 신고하는 유령 경보가 생긴다.
    """
    if not items:
        return None, []
    blocked: list[str] = []
    for item in items:
        snippet = item.get("snippet") or {}
        hits = matched_terms(blocklist_text(snippet), terms)
        if hits:
            blocked.append(f"{snippet.get('title', '')} ← {', '.join(hits)}")
    return (len(items) - len(blocked)) / len(items), blocked


def run(args: argparse.Namespace, budget_box: dict[str, Any] | None = None) -> int:
    now = datetime.now(timezone.utc)
    tax: Taxonomy = load_taxonomy(args.taxonomy)
    allowlist: Allowlist = load_allowlist(args.allowlist)
    terms = tax.all_blocklist_terms
    collector = AlertCollector()

    logger.info(
        "화이트리스트 %d채널 점검 시작 (예시 항목 %d건 제외)",
        allowlist.size,
        len(allowlist.placeholders),
    )
    if allowlist.placeholders:
        collector.add(**alert_specs.allowlist_placeholders(len(allowlist.placeholders)))
    if allowlist.is_undersized:
        logger.warning("화이트리스트 %d채널 < 최소 %d채널", allowlist.size, MIN_ALLOWLIST_SIZE)
        collector.add(**alert_specs.allowlist_undersized(allowlist.size, MIN_ALLOWLIST_SIZE))

    budget = QuotaBudget(hard_cap=args.hard_cap)
    if budget_box is not None:
        budget_box["budget"] = budget  # 중단돼도 실제 소모량을 기록할 수 있게 공유
    client = _make_client(args, tax, budget)

    found: dict[str, dict[str, Any]] = {}
    if allowlist.channels:
        for item in client.channels(list(allowlist.active_ids)):
            found[str(item["id"])] = item

    health = [
        check_channel(entry, found.get(entry.channel_id), client, terms, now.date(), now, collector)
        for entry in allowlist.channels
    ]

    payload = {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allowlist_size": allowlist.size,
        "placeholder_count": len(allowlist.placeholders),
        "thresholds": {
            "min_allowlist_size": MIN_ALLOWLIST_SIZE,
            "no_upload_days": NO_UPLOAD_DAYS,
            "min_blocklist_pass_rate": MIN_BLOCKLIST_PASS_RATE,
            "review_overdue_days": REVIEW_OVERDUE_DAYS,
        },
        "quota_spent": budget.spent,
        "channels": [h.to_json() for h in health],
        "alerts": collector.to_json(),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, args.out)

    logger.info("%s 기록 — 경보 %d건, 소모 %d units", args.out, len(collector), budget.spent)
    for alert in collector.alerts:
        logger.warning("  [%s] %s", alert.severity, alert.title)
    return EXIT_OK


def _make_client(args: argparse.Namespace, tax: Taxonomy, budget: QuotaBudget) -> Client:
    if args.dry_run:
        logger.info("드라이런 — API를 호출하지 않는다")
        return DryRunClient(budget, tax.all_blocklist_terms)
    return YouTubeClient(os.environ.get("YOUTUBE_API_KEY", ""), budget)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="화이트리스트 채널 건강 점검")
    parser.add_argument("--taxonomy", type=Path, default=root / "taxonomy.yaml")
    parser.add_argument("--allowlist", type=Path, default=root / "channel_allowlist.yaml")
    parser.add_argument("--out", type=Path, default=root / "dist" / "channel_health.json")
    parser.add_argument("--hard-cap", type=int, default=DEFAULT_HARD_CAP)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--quota-log",
        type=Path,
        default=root / DEFAULT_LOG,
        help=f"일일 소모 기록 파일 (기본 {DEFAULT_LOG}, 커밋하지 않는다)",
    )
    parser.add_argument("--daily-ceiling", type=int, default=DAILY_CEILING)
    parser.add_argument(
        "--no-quota-log", action="store_true", help="일일 누적 검사·기록을 건너뛴다"
    )
    parser.add_argument(
        "--no-reserve-actions-batch",
        dest="reserve_actions_batch",
        action="store_false",
        help="Actions 일일 배치 몫을 미리 빼두지 않는다",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # 이 스크립트는 배치 뒤에 이어서 도는 일이 많다. 그날 누적을 보지 않으면
    # 배치가 이미 한도 근처까지 쓴 뒤에 25 units를 더 얹어 넘길 수 있다.
    estimate = 25
    if not args.dry_run and not args.no_quota_log:
        try:
            usage, reserve = check_daily_quota(
                args.quota_log,
                estimate,
                ceiling=args.daily_ceiling,
                reserve_actions_batch=args.reserve_actions_batch,
            )
            print(quota_table(usage, estimate, reserve, args.daily_ceiling))
        except QuotaBudgetExceeded as exc:
            logger.error("%s", exc)
            return EXIT_QUOTA

    budget_box: dict[str, Any] = {}
    exit_code = EXIT_RETRYABLE
    try:
        exit_code = run(args, budget_box)
        return exit_code
    except QuotaExceeded as exc:
        logger.error("쿼터 중단: %s", exc)
        exit_code = EXIT_QUOTA
        return EXIT_QUOTA
    except Exception as exc:  # noqa: BLE001
        logger.exception("채널 점검 실패: %s", exc)
        exit_code = EXIT_RETRYABLE
        return EXIT_RETRYABLE
    finally:
        budget = budget_box.get("budget")
        spent = budget.spent if budget is not None else 0
        if not args.dry_run and not args.no_quota_log and spent > 0:
            usage = record_quota(
                args.quota_log,
                script="check_channels",
                units=spent,
                exit_code=exit_code,
            )
            logger.info(
                "쿼터 기록 — 이번 %s units, 오늘(PT %s) 누적 %s units",
                f"{spent:,}", usage.date, f"{usage.spent:,}",
            )


if __name__ == "__main__":
    raise SystemExit(main())
