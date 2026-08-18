#!/usr/bin/env python
"""위기 카테고리 화이트리스트 후보 수집 — 일회성 도구.

    ⚠ 이 스크립트는 배치·워크플로에 넣지 않는다.
      매일 돌 필요가 없고(채널은 한 번 정하면 거의 안 바뀐다), 600 units를 쓰며,
      결과는 사람이 읽고 판단해야 하는 검토 시트다. 자동화할 수 있는 성격이 아니다.
      정기 점검은 check_channels.py가 맡는다.

하는 일
    1. taxonomy.yaml의 위기 전용 search_queries 6개로 검색 (600 units)
    2. 결과 영상의 채널을 등장 횟수 순으로 집계
       (search.list 응답의 snippet.channelId를 쓰므로 집계에는 추가 쿼터가 들지 않는다)
    3. 상위 N개 채널의 구독자 수·총 영상 수·최근 업로드일 조회
    4. uploads 재생목록에서 최근 영상 10개의 제목·길이 수집
    5. blocklist tier_a+b+c 통과율 계산
    6. channel_candidates.md 생성 — 검토 시트 + 붙여넣기용 YAML 블록

쿼터 (기본 --top 30 기준)
    search.list         6회 × 100 = 600
    channels.list       1회 ×   1 =   1
    playlistItems.list 30회 ×   1 =  30   (채널당 1회)
    videos.list        30회 ×   1 =  30   (채널당 1회 — 10건씩이라 50건 배치로 묶이지 않는다)
    -------------------------------------
    합계                           =  661

    배치와 같은 날 돌리면 하루 예산을 함께 쓴다. 배치가 약 7,900을 쓰므로
    같은 날 실행해도 한도 안에 들어오지만, 여유를 두려면 다른 날에 돌린다.

사용 예
    python scripts/suggest_channels.py --dry-run
    python scripts/suggest_channels.py --top 30 --reviewer platformdev03
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.allowlist import NO_UPLOAD_DAYS, load_allowlist
from lib.filters import blocklist_text, parse_duration
from lib.normalize import matched_terms
from lib.quota import COST, QuotaBudget, QuotaExceeded
from lib.actions_status import batch_succeeded_on
from lib.quota_log import (
    DAILY_CEILING,
    DEFAULT_LOG,
    QuotaBudgetExceeded,
    check as check_daily_quota,
    record as record_quota,
    table as quota_table,
)
from lib.taxonomy import MIN_DURATION_SECONDS, Taxonomy, load_taxonomy
from lib.youtube import Client, DryRunClient, YouTubeClient

logger = logging.getLogger("suggest_channels")

RECENT_VIDEO_COUNT = 10  # 채널당 살펴볼 최근 영상 수
DEFAULT_TOP = 30
DEFAULT_HARD_CAP = 1_200

EXIT_OK = 0
EXIT_RETRYABLE = 1
EXIT_QUOTA = 2


@dataclass
class RecentVideo:
    title: str
    duration_seconds: int
    published_at: str
    blocked_by: list[str] = field(default_factory=list)

    @property
    def is_short(self) -> bool:
        return self.duration_seconds < MIN_DURATION_SECONDS

    @property
    def duration_text(self) -> str:
        if self.duration_seconds <= 0:
            return "?"
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


@dataclass
class Candidate:
    channel_id: str
    title: str
    appearances: int
    subscribers: int | None = None
    video_count: int | None = None
    last_upload_at: str | None = None
    days_since_upload: int | None = None
    recent: list[RecentVideo] = field(default_factory=list)
    already_listed: bool = False
    alive: bool = True

    @property
    def pass_rate(self) -> float | None:
        if not self.recent:
            return None
        return sum(1 for v in self.recent if not v.blocked_by) / len(self.recent)

    @property
    def short_ratio(self) -> float | None:
        if not self.recent:
            return None
        return sum(1 for v in self.recent if v.is_short) / len(self.recent)

    @property
    def warnings(self) -> list[str]:
        """객관적으로 확인 가능한 실격 사유만 모은다. 선정 기준 1~3은 사람 몫이다."""
        issues: list[str] = []
        if not self.alive:
            issues.append("채널 조회 실패")
            return issues
        if not self.recent:
            issues.append("최근 영상을 가져오지 못함")
            return issues
        if (self.pass_rate or 0) < 1.0:
            blocked = sum(1 for v in self.recent if v.blocked_by)
            issues.append(f"blocklist 차단 {blocked}건")
        if self.days_since_upload is None or self.days_since_upload > NO_UPLOAD_DAYS:
            issues.append(f"{NO_UPLOAD_DAYS}일 내 업로드 없음")
        if (self.short_ratio or 0) >= 0.5:
            issues.append("최근 영상 절반 이상이 3분 미만")
        return issues

    @property
    def auto_ok(self) -> bool:
        return not self.warnings

    @property
    def name_for_yaml(self) -> str:
        """채널명에 콜론·따옴표가 들어가도 YAML이 깨지지 않게 감싼다."""
        return '"{}"'.format(self.title.replace('"', "'"))


# =============================================================================
# 수집
# =============================================================================


def collect_appearances(
    client: Client, tax: Taxonomy
) -> tuple[Counter[str], dict[str, str]]:
    """위기 전용 검색어로 검색해 채널별 등장 횟수를 센다.

    search.list 응답의 snippet에 channelId/channelTitle이 이미 들어 있어
    집계에는 추가 쿼터가 들지 않는다.
    """
    counter: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for query in tax.crisis_queries:
        items = client.search_items(query)
        for item in items:
            snippet = item.get("snippet") or {}
            channel_id = str(snippet.get("channelId", ""))
            if not channel_id:
                continue
            counter[channel_id] += 1
            titles.setdefault(channel_id, str(snippet.get("channelTitle", "")))
        logger.info("  %-24s → 영상 %d건", query, len(items))
    return counter, titles


def inspect_candidates(
    client: Client,
    tax: Taxonomy,
    counter: Counter[str],
    titles: dict[str, str],
    listed: set[str],
    top: int,
    now: datetime,
) -> list[Candidate]:
    """상위 채널의 상세 정보와 최근 영상을 조사한다."""
    ranked = [cid for cid, _ in counter.most_common(top)]
    found = {str(item["id"]): item for item in client.channels(ranked)}
    terms = tax.all_blocklist_terms

    candidates: list[Candidate] = []
    for channel_id in ranked:
        item = found.get(channel_id)
        candidate = Candidate(
            channel_id=channel_id,
            title=titles.get(channel_id, "(이름 미확인)"),
            appearances=counter[channel_id],
            already_listed=channel_id in listed,
            alive=item is not None,
        )
        if item is not None:
            _fill_channel_stats(candidate, item)
            _fill_recent_videos(candidate, client, item, terms, now)
        candidates.append(candidate)
    return candidates


def _fill_channel_stats(candidate: Candidate, item: dict[str, Any]) -> None:
    stats = item.get("statistics") or {}
    candidate.title = str((item.get("snippet") or {}).get("title", candidate.title))
    if not stats.get("hiddenSubscriberCount") and "subscriberCount" in stats:
        candidate.subscribers = int(stats["subscriberCount"])
    if "videoCount" in stats:
        candidate.video_count = int(stats["videoCount"])


def _fill_recent_videos(
    candidate: Candidate,
    client: Client,
    item: dict[str, Any],
    terms: tuple[str, ...],
    now: datetime,
) -> None:
    uploads = (
        (item.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
    )
    if not uploads:
        return
    video_ids = client.playlist_items(str(uploads), RECENT_VIDEO_COUNT)
    if not video_ids:
        return

    for video in client.videos(video_ids):
        snippet = video.get("snippet") or {}
        # 매칭 범위는 배치와 같아야 한다 — 여기서 따로 조립하지 않고 filters에 맡긴다.
        text = blocklist_text(snippet)
        candidate.recent.append(
            RecentVideo(
                title=str(snippet.get("title", "")),
                duration_seconds=parse_duration(
                    str((video.get("contentDetails") or {}).get("duration", ""))
                ),
                published_at=str(snippet.get("publishedAt", "")),
                blocked_by=matched_terms(text, terms),
            )
        )

    published = [v.published_at for v in candidate.recent if v.published_at]
    if published:
        candidate.last_upload_at = max(published)
        try:
            moment = datetime.fromisoformat(candidate.last_upload_at.replace("Z", "+00:00"))
            candidate.days_since_upload = (now - moment.astimezone(timezone.utc)).days
        except ValueError:
            candidate.days_since_upload = None


# =============================================================================
# 검토 시트 출력
# =============================================================================


def render_markdown(
    candidates: list[Candidate],
    tax: Taxonomy,
    *,
    now: datetime,
    spent: int,
    total_channels: int,
    total_videos: int,
    reviewer: str,
    dry_run: bool,
) -> str:
    lines = [
        "# 위기 카테고리 화이트리스트 후보 검토 시트",
        "",
        f"- 생성: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        + ("  **(드라이런 — 실제 데이터 아님)**" if dry_run else ""),
        f"- 검색어 {len(tax.crisis_queries)}개에서 영상 {total_videos}건 수집 → "
        f"채널 {total_channels}개 집계 → 상위 {len(candidates)}개 조사",
        f"- 소모 쿼터: {spent:,} units",
        "",
        _render_howto(),
        "",
        "## 요약",
        "",
        "| # | 채널명 | 등장 | 구독자 | 총영상 | 최근 업로드 | 통과율 | 3분미만 | 자동 점검 |",
        "|---:|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for index, c in enumerate(candidates, start=1):
        lines.append(_render_summary_row(index, c))

    lines += ["", "## 채널별 최근 영상", ""]
    for index, c in enumerate(candidates, start=1):
        lines += _render_detail(index, c)

    lines += _render_yaml_block(candidates, now, reviewer)
    return "\n".join(lines) + "\n"


def _render_howto() -> str:
    return "\n".join(
        [
            "## 읽는 법",
            "",
            "**자동 점검은 객관적으로 확인 가능한 것만 봅니다.** blocklist 통과율, 최근 업로드 여부,",
            "영상 길이 분포입니다. 아래 선정 기준 3가지는 자동으로 판단할 수 없으므로",
            "최근 영상 제목을 직접 읽고 필요하면 영상을 열어 확인하세요.",
            "",
            "1. 이완·명상·자연 소리·수면 등 **정적인 콘텐츠를 꾸준히** 올리는 채널",
            "2. **자극적 썸네일·낚시성 제목**을 쓰지 않는 채널",
            "3. 공신력 있는 **정신건강 기관·전문가** 채널",
            "",
            "`자동 점검` 열이 통과여도 승인이 아닙니다. 실격 사유가 없다는 뜻일 뿐입니다.",
            "특히 **썸네일은 자동 점검이 보지 못합니다** — 제목이 멀쩡해도 썸네일이 자극적인 채널이 있습니다.",
        ]
    )


def _render_summary_row(index: int, c: Candidate) -> str:
    subs = f"{c.subscribers:,}" if c.subscribers is not None else "비공개"
    videos = f"{c.video_count:,}" if c.video_count is not None else "-"
    upload = (
        f"{c.last_upload_at[:10]} ({c.days_since_upload}일 전)"
        if c.last_upload_at and c.days_since_upload is not None
        else "확인 불가"
    )
    rate = f"{c.pass_rate:.0%}" if c.pass_rate is not None else "-"
    short = f"{c.short_ratio:.0%}" if c.short_ratio is not None else "-"
    if c.already_listed:
        verdict = "이미 등록됨"
    elif c.auto_ok:
        verdict = "통과"
    else:
        verdict = " / ".join(c.warnings)
    return (
        f"| {index} | {_escape(c.title)} | {c.appearances} | {subs} | {videos} | "
        f"{upload} | {rate} | {short} | {verdict} |"
    )


def _render_detail(index: int, c: Candidate) -> list[str]:
    head = f"### {index}. {c.title}"
    if c.already_listed:
        head += "  — 이미 등록됨"
    elif not c.auto_ok:
        head += f"  — {' / '.join(c.warnings)}"
    lines = [head, "", f"`{c.channel_id}`", ""]
    if not c.recent:
        lines += ["최근 영상을 가져오지 못했습니다.", ""]
        return lines
    lines += ["| # | 제목 | 길이 | blocklist |", "|---:|---|---:|---|"]
    for i, v in enumerate(c.recent, start=1):
        flag = f"차단: {', '.join(v.blocked_by)}" if v.blocked_by else ""
        short = " (3분 미만)" if v.is_short else ""
        lines.append(f"| {i} | {_escape(v.title)} | {v.duration_text}{short} | {flag} |")
    lines.append("")
    return lines


def _render_yaml_block(
    candidates: list[Candidate], now: datetime, reviewer: str
) -> list[str]:
    ready = [c for c in candidates if c.auto_ok and not c.already_listed]
    skipped = [c for c in candidates if not c.auto_ok and not c.already_listed]
    today = now.strftime("%Y-%m-%d")

    lines = [
        "## channel_allowlist.yaml 붙여넣기용 블록",
        "",
        f"자동 점검을 통과한 {len(ready)}개만 담았습니다. "
        f"실격 사유가 있는 {len(skipped)}개는 제외했으니, 직접 확인 후 필요하면 손으로 추가하세요.",
        "",
        "**붙여넣기 전에 각 항목의 `note`를 실제 판단 근거로 고쳐 주세요.** "
        "지금 값은 자동 수집된 사실일 뿐 선정 이유가 아닙니다.",
        "",
        "```yaml",
    ]
    if not ready:
        lines += ["# 자동 점검을 통과한 후보가 없습니다.", "```", ""]
        return lines

    for c in ready:
        upload = c.last_upload_at[:10] if c.last_upload_at else "확인 불가"
        lines += [
            f"  # TODO(검토): 최근 영상 제목을 확인하고 선정 기준 1~3 판단 후 note를 고칠 것",
            f"  - channel_id: {c.channel_id}",
            f"    channel_name: {c.name_for_yaml}",
            f'    added_at: "{today}"',
            f'    last_reviewed_at: "{today}"',
            f"    reviewed_by: {reviewer}",
            f"    note: >",
            f"      [자동 수집] 위기 검색어에 {c.appearances}회 등장, "
            f"최근 영상 {len(c.recent)}건 blocklist 통과율 "
            f"{(c.pass_rate or 0):.0%}, 마지막 업로드 {upload}.",
            f"      선정 기준 1~3에 대한 판단을 여기에 적을 것.",
            "",
        ]
    lines += ["```", ""]
    return lines


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


# =============================================================================
# 진입점
# =============================================================================


def print_estimate(tax: Taxonomy, top: int, hard_cap: int) -> int:
    rows = [
        ("위기 전용 검색", "search.list", len(tax.crisis_queries)),
        ("후보 채널 조회", "channels.list", -(-top // 50)),
        ("채널별 최근 업로드", "playlistItems.list", top),
        # 최근 영상은 채널마다 따로 조회하므로 채널 수만큼 호출된다.
        # (채널당 10건이라 50건 배치로 묶이지 않는다)
        ("최근 영상 상세", "videos.list", top),
    ]
    total = sum(COST[endpoint] * calls for _, endpoint, calls in rows)
    print("\n예상 쿼터 소모량 (실행 전 산정)")
    print("=" * 60)
    print(f"  {'항목':<28}{'호출':>8}{'units':>12}")
    print("-" * 60)
    for label, endpoint, calls in rows:
        print(f"  {label:<28}{calls:>8,}{COST[endpoint] * calls:>12,}")
    print("-" * 60)
    print(f"  {'합계':<28}{'':>8}{total:>12,}")
    print(f"  하드캡 {hard_cap:,} → 여유 {hard_cap - total:,} units")
    print("=" * 60)
    return total


def run(args: argparse.Namespace, budget_box: dict[str, Any] | None = None) -> int:
    now = datetime.now(timezone.utc)
    tax = load_taxonomy(args.taxonomy)
    allowlist = load_allowlist(args.allowlist)
    listed = set(allowlist.active_ids)

    logger.info(
        "위기 전용 검색어 %d개로 후보를 모은다 (이미 등록된 채널 %d개는 표시만 하고 제외)",
        len(tax.crisis_queries),
        len(listed),
    )
    estimated = print_estimate(tax, args.top, args.hard_cap)
    if estimated > args.hard_cap:
        logger.error("예상 소모량이 하드캡을 넘는다 — 중단한다")
        return EXIT_QUOTA

    # 하드캡은 "이번 실행 하나"의 상한이고, 아래는 "그날 전체"의 상한이다.
    # 둘 다 있어야 한다 — 이 스크립트는 하루에 여러 번 돌려볼 수 있고,
    # 한 번에 661이면 하드캡(1,200)은 통과하지만 세 번 돌면 배치 몫을 까먹는다.
    # (2026-08-18까지 check를 import만 하고 부르지 않아 이 검사가 빠져 있었다.
    #  --daily-ceiling·--no-reserve-actions-batch 플래그도 아무 일을 하지 않았다.)
    if not args.dry_run and not args.no_quota_log:
        try:
            usage, reserve = check_daily_quota(
                args.quota_log,
                estimated,
                ceiling=args.daily_ceiling,
                reserve_actions_batch=args.reserve_actions_batch,
                batch_probe=batch_succeeded_on,
            )
        except QuotaBudgetExceeded as exc:
            logger.error("%s", exc)
            logger.error(
                "그날 이미 쓴 양을 포함한 판단이다. "
                "정말 실행하려면 --no-quota-log, Actions 배치 예약을 빼려면 "
                "--no-reserve-actions-batch."
            )
            return EXIT_QUOTA
        print(quota_table(usage, estimated, reserve, args.daily_ceiling))

    budget = QuotaBudget(hard_cap=args.hard_cap)
    if budget_box is not None:
        budget_box["budget"] = budget  # 중단돼도 실제 소모량을 기록할 수 있게 공유
    client: Client = (
        DryRunClient(budget, tax.all_blocklist_terms)
        if args.dry_run
        else YouTubeClient(os.environ.get("YOUTUBE_API_KEY", ""), budget)
    )
    if args.dry_run:
        logger.info("드라이런 — API를 호출하지 않는다")

    counter, titles = collect_appearances(client, tax)
    total_videos = sum(counter.values())
    logger.info("영상 %d건에서 채널 %d개 집계", total_videos, len(counter))

    candidates = inspect_candidates(
        client, tax, counter, titles, listed, args.top, now
    )
    ready = sum(1 for c in candidates if c.auto_ok and not c.already_listed)
    logger.info(
        "상위 %d개 조사 완료 — 자동 점검 통과 %d개, 실격 %d개, 이미 등록 %d개",
        len(candidates),
        ready,
        sum(1 for c in candidates if not c.auto_ok and not c.already_listed),
        sum(1 for c in candidates if c.already_listed),
    )

    markdown = render_markdown(
        candidates,
        tax,
        now=now,
        spent=budget.spent,
        total_channels=len(counter),
        total_videos=total_videos,
        reviewer=args.reviewer,
        dry_run=args.dry_run,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")

    logger.info("%s 기록 — 소모 %d units", args.out, budget.spent)
    logger.info("사람이 읽고 판단할 차례다. 붙여넣기용 YAML 블록은 문서 맨 아래에 있다.")
    return EXIT_OK


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="위기 카테고리 화이트리스트 후보 수집 (일회성 도구)"
    )
    parser.add_argument("--taxonomy", type=Path, default=root / "taxonomy.yaml")
    parser.add_argument("--allowlist", type=Path, default=root / "channel_allowlist.yaml")
    parser.add_argument("--out", type=Path, default=root / "channel_candidates.md")
    parser.add_argument(
        "--top", type=int, default=DEFAULT_TOP, help=f"조사할 상위 채널 수 (기본 {DEFAULT_TOP})"
    )
    parser.add_argument(
        "--reviewer",
        default=os.environ.get("REVIEWER") or os.environ.get("USERNAME") or "TODO",
        help="YAML 블록의 reviewed_by 값",
    )
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
        logger.exception("후보 수집 실패: %s", exc)
        exit_code = EXIT_RETRYABLE
        return EXIT_RETRYABLE
    finally:
        budget = budget_box.get("budget")
        spent = budget.spent if budget is not None else 0
        if not args.dry_run and not args.no_quota_log and spent > 0:
            usage = record_quota(
                args.quota_log,
                script="suggest_channels",
                units=spent,
                exit_code=exit_code,
            )
            logger.info(
                "쿼터 기록 — 이번 %s units, 오늘(PT %s) 누적 %s units",
                f"{spent:,}", usage.date, f"{usage.spent:,}",
            )


if __name__ == "__main__":
    raise SystemExit(main())
