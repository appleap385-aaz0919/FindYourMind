#!/usr/bin/env python
"""videos.json 생성 배치 (PLAN.md Phase 1).

taxonomy.yaml을 읽어 세분류별로 YouTube를 검색하고, 검증·필터를 거쳐
정적 배포용 videos.json을 만든다.

실행 원칙 4가지 (PLAN.md Phase 1 확정):
  1. 위기 카테고리를 가장 먼저 처리한다.
     중단이 발생해도 안전 관련 데이터는 이미 갱신된 상태여야 한다.
     부수 효과로, 위기 풀을 먼저 확정하면 일반 카테고리에서 그 videoId를 후보 단계에서
     제외할 수 있어 crisis ↔ categories 상호 배타가 구조적으로 보장된다.
  2. 실행 전 예상 쿼터를 산정해 하드캡(9,800)을 넘으면 API를 한 번도 부르지 않고 중단한다.
  3. 중단 시 원자성 — 부분 결과를 절대 쓰지 않는다.
     파일은 모든 처리가 끝난 뒤 한 번에, tmp → os.replace로 교체한다.
     빌드가 실패하면 워크플로가 배포 단계를 건너뛰므로 직전 videos.json이 그대로 유지된다.
  4. 위기 카테고리 확보량이 12건 미만이면 필터를 완화하지 않고 직전 결과를 유지한다.
  5. 위기 카테고리는 채널을 라운드로빈으로 순회하며 채우고, 한 채널이 3건을 넘게
     차지하지 못한다 (일반 카테고리는 제외). 순회 시작 지점은 day_of_year로 매일 돌려
     뒤쪽 채널이 구조적으로 배제되지 않게 한다.
     20건을 못 채울 때만 4, 5로 완화하고, 그래도 12건이 안 되면 상한을 해제한다.
     상세는 select_crisis_videos()와 taxonomy.yaml content_policy.max_per_channel 참조.

종료 코드:
  0  성공
  1  일반 오류 — 워크플로가 1회만 재시도한다
  2  쿼터 관련 중단 — 재시도해도 같은 결과이므로 재시도하지 않는다

사용 예:
  python scripts/build_videos.py --dry-run
  python scripts/build_videos.py --previous _previous/data/videos.json --out-dir dist
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import alerts as alert_specs
from lib.alerts import AlertCollector
from lib.allowlist import MIN_ALLOWLIST_SIZE, Allowlist, load_allowlist
from lib.filters import FilterStats, Video, apply_filters, dedupe
from lib.normalize import normalize
from lib.quota import DEFAULT_HARD_CAP, QuotaBudget, QuotaExceeded, build_estimate
from lib.taxonomy import (
    CATEGORY_MAX_VIDEOS,
    CATEGORY_MIN_VIDEOS,
    CRISIS_MAX_VIDEOS,
    CRISIS_MIN_VIDEOS,
    CRISIS_STALE_DAYS,
    MIN_DURATION_SECONDS,
    Subcategory,
    Taxonomy,
    load_taxonomy,
)
from lib.youtube import Client, DryRunClient, YouTubeClient

logger = logging.getLogger("build_videos")

# 화이트리스트 채널 1개당 읽어올 최근 업로드 수 (playlistItems 1회 = 1 unit)
UPLOADS_PER_CHANNEL = 15

# --only에서 위기 카테고리를 가리키는 토큰. taxonomy의 세분류 id 공간과 겹치지 않는다.
CRISIS_SELECTOR = "safety.crisis"

EXIT_OK = 0
EXIT_RETRYABLE = 1
EXIT_QUOTA = 2


class IntegrityError(RuntimeError):
    """산출물 무결성 위반. 배포하지 않는다."""


class GuardrailError(RuntimeError):
    """위기 카테고리 가드레일 위반. 검색을 시작하지 않는다."""


class SelectionError(ValueError):
    """--only에 알 수 없는 세분류가 지정됐다."""


@dataclass
class CrisisResult:
    videos: list[dict[str, str]]
    updated_at: str
    source: str
    carried_over: bool
    stats: FilterStats | None = None
    max_per_channel: int | None = None  # 실제로 적용된 채널당 상한
    per_channel_unlocked: bool = False  # 12건 최소치를 지키려 상한을 해제했는가

    @property
    def video_ids(self) -> set[str]:
        return {v["videoId"] for v in self.videos}

    @property
    def channel_spread(self) -> dict[str, int]:
        return dict(Counter(v["channel"] for v in self.videos).most_common())


@dataclass
class CategoryResult:
    id: str
    parent: str
    label: str
    videos: list[dict[str, str]]
    stats: FilterStats
    queries: list[str]
    from_previous: int = 0
    excluded_by_crisis: int = 0
    surplus: int = 0  # 상한 20건을 넘겨 남은 예비 후보. 0이면 풀에 여유가 없다는 뜻

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent": self.parent,
            "label": self.label,
            "videos": self.videos,
        }


@dataclass
class BuildContext:
    tax: Taxonomy
    client: Client
    budget: QuotaBudget
    previous: dict[str, Any]
    collector: AlertCollector = field(default_factory=AlertCollector)


# =============================================================================
# 위기 카테고리 (가장 먼저 실행)
# =============================================================================


def verify_query_guardrail(tax: Taxonomy) -> None:
    """가드레일 1 — 전용 검색어가 금지 패턴을 포함하지 않는지 검색 전에 확인한다.

    한 건이라도 위반하면 API를 부르지 않고 배치를 실패시킨다.
    검색이 끝난 뒤 걸러내는 것보다, 애초에 그런 질의를 던지지 않는 게 맞다.
    """
    violations: list[str] = []
    for query in tax.crisis_queries:
        normalized = normalize(query)
        for pattern in tax.forbidden_query_patterns:
            needle = normalize(pattern)
            if needle and needle in normalized:
                violations.append(f"{query!r} ← 금지 패턴 {pattern!r}")
    if violations:
        raise GuardrailError(
            "위기 카테고리 검색어가 forbidden_query_patterns를 위반한다:\n  "
            + "\n  ".join(violations)
        )
    logger.info(
        "가드레일 1 통과 — 전용 검색어 %d개, 금지 패턴 %d개 검사",
        len(tax.crisis_queries),
        len(tax.forbidden_query_patterns),
    )


def collect_allowlist_candidates(
    client: Client, allowlist: Allowlist
) -> tuple[list[str], set[str]]:
    """가드레일 2 — 화이트리스트 채널의 최근 업로드를 모은다.

    search.list(channelId)는 채널당 100 units라 쓰지 않는다.
    channels.list로 uploads 재생목록 id를 얻고 playlistItems.list로 읽으면 채널당 1 unit이다.
    """
    if not allowlist.channels:
        logger.warning("화이트리스트가 비어 있다 — 전용 검색 결과만 사용한다")
        return [], set()

    channels = client.channels(list(allowlist.active_ids))
    uploads: dict[str, str] = {}
    for channel in channels:
        playlist = (
            (channel.get("contentDetails") or {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if playlist:
            uploads[str(channel["id"])] = str(playlist)

    missing = set(allowlist.active_ids) - set(uploads)
    if missing:
        logger.warning("uploads 재생목록을 찾지 못한 채널 %d개: %s", len(missing), sorted(missing))

    video_ids: list[str] = []
    for playlist in uploads.values():
        video_ids.extend(client.playlist_items(playlist, UPLOADS_PER_CHANNEL))

    logger.info(
        "화이트리스트 %d채널에서 후보 %d건 수집 (소모 %d units)",
        len(uploads),
        len(video_ids),
        len(uploads) + 1,
    )
    return video_ids, set(uploads)


def build_crisis(
    ctx: BuildContext, allowlist: Allowlist, now: datetime, day_of_year: int
) -> CrisisResult:
    """위기 카테고리 영상 풀을 만든다 (3중 가드레일 전부 적용).

    day_of_year는 채널 라운드로빈의 시작 지점을 돌리는 데만 쓴다
    (일반 카테고리의 검색어 로테이션과 같은 값을 공유한다).
    """
    verify_query_guardrail(ctx.tax)

    allowlist_ids, allowlist_channels = collect_allowlist_candidates(ctx.client, allowlist)

    # 전용 검색은 화이트리스트 충족 여부와 무관하게 항상 실행한다.
    # 안전 장치는 쿼터 절감 대상이 아니며, PLAN.md 예산에도 600 units가 포함되어 있다.
    search_ids: list[str] = []
    for query in ctx.tax.crisis_queries:
        search_ids.extend(ctx.client.search(query))

    ordered = dedupe(allowlist_ids + search_ids)
    logger.info("위기 후보 %d건 (화이트리스트 우선 정렬)", len(ordered))

    items = ctx.client.videos(ordered)
    kept, stats = apply_filters(
        items, ctx.tax.crisis_blocklist(), min_seconds=MIN_DURATION_SECONDS
    )
    logger.info("위기 필터 결과 — %s", stats.summary())
    _log_blocked_samples(stats)

    rank = {vid: i for i, vid in enumerate(ordered)}
    kept.sort(
        key=lambda v: (
            v.channel_id not in allowlist_channels,  # 화이트리스트 채널 우선
            not v.comments_disabled,  # 댓글 사용 중지 영상 우선 (filter_rules)
            rank.get(v.video_id, len(rank)),
        )
    )

    selected, cap, unlocked = select_crisis_videos(
        kept, ctx.tax.crisis_per_channel_ladder, allowlist_channels, day_of_year
    )

    if len(selected) >= CRISIS_MIN_VIDEOS:
        videos = [v.to_json() for v in selected]
        logger.info("위기 카테고리 갱신 — %d건 확보", len(videos))
        return CrisisResult(
            videos=videos,
            updated_at=_iso(now),
            source="whitelist+guarded_search",
            carried_over=False,
            stats=stats,
            max_per_channel=cap,
            per_channel_unlocked=unlocked,
        )

    return _carry_over_crisis(ctx, selected, stats, now)


def select_crisis_videos(
    kept: list[Video],
    ladder: Sequence[int],
    allowlist_channels: set[str],
    day_of_year: int,
) -> tuple[list[Video], int, bool]:
    """채널을 라운드로빈으로 순회하며 최대 CRISIS_MAX_VIDEOS건을 고른다.

    상한이 없으면 정렬 상위 채널이 20슬롯을 독식한다. 화이트리스트 우선 정렬이
    채널별로 연속 배치되는 구조라, 실측에서 10채널 중 2채널이 20건을 전부 가져갔다.
    상한만 두면 편중은 줄지만 순회 뒤쪽 채널이 20슬롯 밖으로 밀려 여전히 0건이다.

    완화 순서 (taxonomy.yaml content_policy.max_per_channel_rationale):
        1. 기본 상한(3)으로 20건이 차면 그대로 쓴다 — 분산이 개수보다 우선이다.
        2. 20건에 못 미치면 4, 5로 한 단계씩 올려 다시 시도한다.
        3. 마지막 단계로도 12건(최소 확보량)을 못 채우는데 상한만 풀면 채울 수
           있는 경우에만 상한을 해제한다. 최소 확보량은 분산보다 우선한다 —
           12건 미달은 위기 카테고리가 통째로 직전 결과로 되돌아간다는 뜻이라
           편중보다 나쁘다. 이때는 분산을 포기하는 것이므로 라운드로빈도 쓰지 않고
           정렬 순서 그대로 채운다.

    반환: (선정 목록, 실제 적용된 상한, 상한 해제 여부)
    """
    last = ladder[-1]
    for cap in ladder:
        picked = _take_round_robin(kept, cap, allowlist_channels, day_of_year)
        if len(picked) >= CRISIS_MAX_VIDEOS:
            _log_spread(picked, cap, unlocked=False)
            return picked, cap, False

    picked = _take_round_robin(kept, last, allowlist_channels, day_of_year)
    # 상한을 풀어도 12건을 못 채우면 해제할 이유가 없다 — 풀 자체가 얕은 것이고,
    # 어차피 호출자가 직전 결과 유지로 넘어간다.
    if len(picked) < CRISIS_MIN_VIDEOS <= len(kept):
        logger.warning(
            "채널당 상한 %d로는 %d건뿐이라 최소 %d건을 못 채운다 — 상한을 해제한다",
            last,
            len(picked),
            CRISIS_MIN_VIDEOS,
        )
        picked = kept[:CRISIS_MAX_VIDEOS]
        _log_spread(picked, last, unlocked=True)
        return picked, last, True

    logger.warning(
        "채널당 상한을 %d까지 올려도 %d건 — 후보 풀이 얕다", last, len(picked)
    )
    _log_spread(picked, last, unlocked=False)
    return picked, last, False


def _take_round_robin(
    videos: list[Video],
    cap: int,
    allowlist_channels: set[str],
    day_of_year: int,
) -> list[Video]:
    """채널을 한 바퀴씩 돌며 1건씩, 채널당 cap건까지 채운다.

    채널 내부 순서는 건드리지 않는다 — 전달받은 정렬(화이트리스트 우선 →
    댓글 사용 중지 → 후보 순위)이 채널 안에서 그대로 유지된다.

    라운드로빈은 화이트리스트 그룹을 **먼저 끝까지 돌린 뒤** 검색 결과 그룹으로
    넘어간다. 두 그룹을 한 바퀴에 섞으면 채널 수가 20개를 넘는 순간 첫 바퀴만으로
    슬롯이 차버려, 화이트리스트가 20슬롯의 절반밖에 못 가져간다.
    (실측: 섞었을 때 화이트리스트 10건 + 검토받지 않은 검색 채널 10건)
    화이트리스트 우선은 가드레일 2 자체라 분산을 위해 양보할 대상이 아니다.
    """
    by_channel: dict[str, list[Video]] = {}
    for video in videos:
        by_channel.setdefault(video.channel_id, []).append(video)

    channel_ids = list(by_channel)
    listed = _rotate([c for c in channel_ids if c in allowlist_channels], day_of_year)
    others = _rotate([c for c in channel_ids if c not in allowlist_channels], day_of_year)

    picked: list[Video] = []
    for group in (listed, others):
        for depth in range(cap):  # depth번째 바퀴 = 채널마다 depth+1번째 영상
            for channel_id in group:
                queue = by_channel[channel_id]
                if depth >= len(queue):
                    continue  # 이 채널은 재고 소진 — 다음 채널로 넘어간다
                picked.append(queue[depth])
                if len(picked) >= CRISIS_MAX_VIDEOS:
                    return picked
    return picked


def _rotate(channel_ids: list[str], day_of_year: int) -> list[str]:
    """순회 시작 지점을 매일 돌린다.

    순서가 고정이면 뒤쪽 채널이 매일 같은 자리에서 20슬롯 밖으로 밀려
    구조적으로 배제된다. 사람이 승인한 화이트리스트가 실질적으로 축소되는 것이다.
    """
    if not channel_ids:
        return []
    start = day_of_year % len(channel_ids)
    return channel_ids[start:] + channel_ids[:start]


def _log_spread(picked: list[Video], cap: int, *, unlocked: bool) -> None:
    spread = Counter(v.channel for v in picked)
    note = " (상한 해제 — 라운드로빈 미적용)" if unlocked else ""
    logger.info(
        "위기 %d건을 %d채널로 분산 — 채널당 상한 %d%s | %s",
        len(picked),
        len(spread),
        cap,
        note,
        ", ".join(f"{name} {n}건" for name, n in spread.most_common()),
    )


def _carry_over_crisis(
    ctx: BuildContext, kept: list[Video], stats: FilterStats, now: datetime
) -> CrisisResult:
    """12건 미달 — 필터를 완화하지 않고 직전 결과를 유지한다."""
    logger.warning(
        "위기 확보량 %d건 < 최소 %d건 — 필터를 완화하지 않고 직전 결과를 유지한다",
        len(kept),
        CRISIS_MIN_VIDEOS,
    )
    ctx.collector.add(**alert_specs.crisis_carried_over(len(kept), CRISIS_MIN_VIDEOS))

    previous = ctx.previous.get("crisis") or {}
    previous_videos = previous.get("videos") or []
    if not previous_videos:
        logger.error("유지할 직전 결과도 없다 — 위기 영상 없이 상담 안내만 노출된다")
        ctx.collector.add(**alert_specs.crisis_empty())
        return CrisisResult(
            videos=[],
            updated_at=str(previous.get("updated_at") or _iso(now)),
            source="none",
            carried_over=True,
            stats=stats,
        )

    # 유지하더라도 생존 검증은 한다. 이건 필터 완화가 아니라 강화 방향이며,
    # 삭제된 영상을 계속 노출하는 쪽이 더 나쁘다.
    previous_ids = [str(v["videoId"]) for v in previous_videos]
    alive_items = ctx.client.videos(previous_ids)
    alive, _ = apply_filters(
        alive_items, ctx.tax.crisis_blocklist(), min_seconds=MIN_DURATION_SECONDS
    )
    order = {vid: i for i, vid in enumerate(previous_ids)}
    alive.sort(key=lambda v: order.get(v.video_id, len(order)))

    logger.warning(
        "직전 결과 %d건 중 %d건 생존 — updated_at은 갱신하지 않는다",
        len(previous_ids),
        len(alive),
    )
    return CrisisResult(
        videos=[v.to_json() for v in alive],
        updated_at=str(previous.get("updated_at") or _iso(now)),
        source=str(previous.get("source", "carried_over")),
        carried_over=True,
        stats=stats,
    )


# =============================================================================
# 일반 카테고리
# =============================================================================


def build_categories(
    ctx: BuildContext,
    day_of_year: int,
    exclude: set[str],
    subcategories: Sequence[Subcategory],
) -> list[CategoryResult]:
    previous_map = {
        str(c["id"]): [str(v["videoId"]) for v in c.get("videos", [])]
        for c in ctx.previous.get("categories", [])
    }
    results: list[CategoryResult] = []
    for sub in subcategories:
        results.append(
            _build_one_category(ctx, sub, day_of_year, exclude, previous_map.get(sub.id, []))
        )
    return results


def _build_one_category(
    ctx: BuildContext,
    sub: Subcategory,
    day_of_year: int,
    exclude: set[str],
    previous_ids: list[str],
) -> CategoryResult:
    queries = ctx.tax.rotated_queries(sub, day_of_year)

    found: list[str] = []
    for query in queries:
        found.extend(ctx.client.search(query))

    # 위기 videoId 제외는 "최종 20건을 고른 뒤"가 아니라 "후보 단계"에서 한다.
    # 후보가 카테고리당 100건 이상이고 슬롯은 20개뿐이라, 제외된 자리는 다음 순위 영상이
    # 그대로 밀고 올라온다. 제외 때문에 카테고리가 빈약해지지 않는다.
    unique_found = dedupe(found)
    new_ids = [vid for vid in unique_found if vid not in exclude]
    excluded_new = len(unique_found) - len(new_ids)

    # 직전 결과를 후보 뒤에 붙여 확보량을 채운다.
    # 로테이션으로 매일 검색어 조합이 달라지므로, merge가 오히려 장기 다양성을 키운다.
    # (PLAN.md Phase 1 "이전 결과와 merge하므로 영상 풀 다양성 손실 없음")
    seen = set(new_ids)
    carried = [vid for vid in previous_ids if vid not in seen and vid not in exclude]
    excluded_previous = sum(
        1 for vid in previous_ids if vid in exclude and vid not in seen
    )
    candidates = new_ids + carried

    items = ctx.client.videos(candidates)
    kept, stats = apply_filters(
        items, ctx.tax.blocklist_for(sub.parent), min_seconds=MIN_DURATION_SECONDS
    )

    rank = {vid: i for i, vid in enumerate(candidates)}
    kept.sort(key=lambda v: rank.get(v.video_id, len(rank)))
    final = kept[:CATEGORY_MAX_VIDEOS]
    from_previous = sum(1 for v in final if v.video_id not in seen)

    excluded = excluded_new + excluded_previous
    logger.info(
        "%-22s 쿼리 %d개 → %s | 위기 제외 %d건(신규 %d/직전 %d), 여유 %d건, 직전 유입 %d건",
        sub.id,
        len(queries),
        stats.summary(),
        excluded,
        excluded_new,
        excluded_previous,
        max(0, len(kept) - len(final)),  # 상한을 넘겨 버려진 예비 후보 수
        from_previous,
    )
    _evaluate_category(ctx, sub, final, stats, excluded)

    return CategoryResult(
        id=sub.id,
        parent=sub.parent,
        label=sub.label,
        videos=[v.to_json() for v in final],
        stats=stats,
        queries=queries,
        from_previous=from_previous,
        excluded_by_crisis=excluded,
        surplus=max(0, len(kept) - len(final)),
    )


def _evaluate_category(
    ctx: BuildContext,
    sub: Subcategory,
    final: list[Video],
    stats: FilterStats,
    excluded: int,
) -> None:
    if stats.is_overfiltered():
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(stats.dropped_by_tier.items()))
        logger.warning(
            "%s 과다 필터링 — blocklist가 후보의 %.0f%%를 제거 (%s)",
            sub.id,
            stats.blocklist_drop_ratio * 100,
            detail,
        )
        _log_blocked_samples(stats)
        ctx.collector.add(
            **alert_specs.category_overfiltered(sub.id, stats.blocklist_drop_ratio, detail)
        )
    if len(final) < CATEGORY_MIN_VIDEOS:
        # 후보 풀이 슬롯보다 훨씬 크므로 위기 제외가 원인인 경우는 사실상 없다.
        # 그래도 원인을 헷갈리지 않도록 제외 건수를 함께 남긴다.
        cause = f" (위기 제외 {excluded}건 포함)" if excluded else ""
        logger.warning(
            "%s 확보량 %d건 < 목표 %d건%s", sub.id, len(final), CATEGORY_MIN_VIDEOS, cause
        )
        ctx.collector.add(
            **alert_specs.category_low_yield(sub.id, len(final), CATEGORY_MIN_VIDEOS)
        )


def _log_blocked_samples(stats: FilterStats) -> None:
    for sample in stats.samples[:3]:
        logger.debug("  걸러냄: %s", sample)


# =============================================================================
# 무결성 검증 · 출력
# =============================================================================


def assert_disjoint(categories: list[CategoryResult], crisis: CrisisResult | None) -> None:
    """crisis와 categories가 videoId를 공유하지 않는지 단언한다 (PLAN.md 4절).

    위기 풀을 먼저 확정하고 일반 카테고리에서 제외했으므로 정상적으로는 통과한다.
    여기서 걸린다면 제외 로직이 깨진 것이므로 배포하지 않는다.
    """
    if crisis is None:
        # --only로 위기를 건너뛴 부분 실행. 검사할 위기 풀 자체가 없다.
        # 이 산출물은 videos.partial.json으로만 나가므로 배포 경로에 닿지 않는다.
        logger.warning("위기 카테고리를 실행하지 않아 상호 배타 검증을 건너뛴다")
        return
    crisis_ids = crisis.video_ids
    for category in categories:
        overlap = {v["videoId"] for v in category.videos} & crisis_ids
        if overlap:
            raise IntegrityError(
                f"crisis와 {category.id}가 videoId를 공유한다: {sorted(overlap)}. "
                "배포를 중단한다."
            )
    logger.info(
        "무결성 검증 통과 — crisis %d건과 일반 %d건이 서로소",
        len(crisis_ids),
        sum(len(c.videos) for c in categories),
    )


def check_crisis_freshness(ctx: BuildContext, crisis: CrisisResult, now: datetime) -> int:
    """crisis.updated_at이 오래 멈춰 있으면 경보를 낸다."""
    updated = _parse_iso(crisis.updated_at)
    if updated is None:
        return -1
    days = (now - updated).days
    if days >= CRISIS_STALE_DAYS:
        logger.error("위기 풀이 %d일째 갱신되지 않았다", days)
        ctx.collector.add(
            **alert_specs.crisis_stale(crisis.updated_at, days, CRISIS_STALE_DAYS)
        )
    return days


def write_outputs(
    out_dir: Path,
    version: str,
    categories: list[CategoryResult],
    crisis: CrisisResult | None,
    ctx: BuildContext,
    *,
    dry_run: bool,
    crisis_age_days: int,
    only: list[str] | None = None,
) -> None:
    """모든 처리가 끝난 뒤에만 호출된다 (부분 결과 방지).

    --only 부분 실행의 산출물은 `videos.partial.json`으로 따로 낸다.
    24개 카테고리가 다 들어 있지 않은 파일이 videos.json 이름으로 남으면
    다음 배포 때 그대로 나갈 수 있다. 이름을 분리하고 version.json도 만들지 않아,
    부분 실행 결과는 어떤 경로로도 배포에 닿지 않는다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    partial = only is not None

    videos_json: dict[str, Any] = {"version": version}
    if partial:
        videos_json["partial"] = True
        videos_json["only"] = only
    videos_json["categories"] = [c.to_json() for c in categories]
    if crisis is not None:
        videos_json["crisis"] = {
            "updated_at": crisis.updated_at,
            "source": crisis.source,
            "videos": crisis.videos,
        }

    report_json = {
        "version": version,
        "dry_run": dry_run,
        "partial": partial,
        "only": only,
        "quota_spent": ctx.budget.spent,
        "quota_calls": dict(ctx.budget.calls),
        "crisis": None
        if crisis is None
        else {
            "count": len(crisis.videos),
            "carried_over": crisis.carried_over,
            "updated_at": crisis.updated_at,
            "age_days": crisis_age_days,
            "max_per_channel": crisis.max_per_channel,
            "per_channel_unlocked": crisis.per_channel_unlocked,
            "channel_spread": crisis.channel_spread,
            "filters": crisis.stats.to_json() if crisis.stats else None,
        },
        "categories": [
            {
                "id": c.id,
                "count": len(c.videos),
                "from_previous": c.from_previous,
                "excluded_by_crisis": c.excluded_by_crisis,
                "surplus": c.surplus,
                "queries": c.queries,
                "filters": c.stats.to_json(),
            }
            for c in categories
        ],
        "alerts": ctx.collector.to_json(),
    }

    if partial:
        _atomic_write(out_dir / "videos.partial.json", videos_json)
        _atomic_write(out_dir / "build_report.partial.json", report_json)
        logger.warning(
            "부분 실행 산출물 — %s/videos.partial.json (version.json 미생성, 배포 대상 아님)",
            out_dir,
        )
        return

    _atomic_write(out_dir / "videos.json", videos_json)
    # 앱이 매일 500KB를 받지 않도록 버전만 담은 경량 파일을 따로 낸다.
    _atomic_write(
        out_dir / "version.json",
        {"version": version, "crisis_updated_at": crisis.updated_at},  # type: ignore[union-attr]
    )
    _atomic_write(out_dir / "build_report.json", report_json)
    logger.info("산출물 기록 완료 — %s", out_dir)


def _atomic_write(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def load_previous(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        logger.warning("직전 videos.json이 없다 — 최초 실행으로 진행한다")
        return {}
    try:
        with path.open(encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("직전 videos.json을 읽지 못했다 (%s) — 최초 실행으로 진행한다", exc)
        return {}
    logger.info(
        "직전 결과 로드 — version=%s, 카테고리 %d개, 위기 %d건",
        data.get("version"),
        len(data.get("categories", [])),
        len((data.get("crisis") or {}).get("videos", [])),
    )
    return data


# =============================================================================
# 진입점
# =============================================================================


def resolve_selection(
    tax: Taxonomy, only: str | None
) -> tuple[list[Subcategory], bool, list[str] | None]:
    """--only 인자를 (실행할 세분류, 위기 실행 여부, 원본 선택 목록)으로 푼다.

    전체 7,900 units를 쓰기 전에 소량으로 실제 API 응답을 확인하기 위한 옵션이다.
    위기 카테고리는 `safety.crisis`로 지정한다.
    """
    if not only:
        return list(tax.subcategories), True, None

    requested = [token.strip() for token in only.split(",") if token.strip()]
    known = {sub.id: sub for sub in tax.subcategories}
    unknown = [t for t in requested if t != CRISIS_SELECTOR and t not in known]
    if unknown:
        raise SelectionError(
            f"알 수 없는 세분류: {', '.join(unknown)}\n"
            f"사용 가능한 값: {CRISIS_SELECTOR}, " + ", ".join(known)
        )

    run_crisis = CRISIS_SELECTOR in requested
    # taxonomy 순서를 유지한다 — 로테이션 위상(subcategory index)이 순서가 아니라
    # sub.index에 묶여 있어야 전체 실행과 같은 검색어가 선택된다.
    selected = [sub for sub in tax.subcategories if sub.id in set(requested)]
    return selected, run_crisis, requested


def preflight(
    tax: Taxonomy,
    allowlist: Allowlist,
    previous: dict[str, Any],
    day_of_year: int,
    hard_cap: int,
    subcategories: Sequence[Subcategory],
    run_crisis: bool,
) -> int:
    """실행 전 예상 쿼터를 산정해 로그로 출력하고 총량을 반환한다."""
    category_calls = sum(len(tax.rotated_queries(s, day_of_year)) for s in subcategories)
    crisis_calls = len(tax.crisis_queries) if run_crisis else 0
    channels = len(allowlist.channels) if run_crisis else 0

    selected_ids = {s.id for s in subcategories}
    previous_ids = sum(
        len(c.get("videos", []))
        for c in previous.get("categories", [])
        if str(c.get("id")) in selected_ids
    )
    expected_ids = (
        (category_calls + crisis_calls) * 50 + channels * UPLOADS_PER_CHANNEL + previous_ids
    )

    estimate = build_estimate(
        category_search_calls=category_calls,
        crisis_search_calls=crisis_calls,
        allowlist_channels=channels,
        expected_video_ids=expected_ids,
    )
    print(estimate.table(hard_cap))
    return estimate.total


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="videos.json 생성 배치")
    parser.add_argument("--taxonomy", type=Path, default=root / "taxonomy.yaml")
    parser.add_argument("--allowlist", type=Path, default=root / "channel_allowlist.yaml")
    parser.add_argument("--out-dir", type=Path, default=root / "dist")
    parser.add_argument(
        "--previous", type=Path, default=None, help="직전 배치의 videos.json 경로"
    )
    parser.add_argument("--hard-cap", type=int, default=DEFAULT_HARD_CAP)
    parser.add_argument(
        "--day-of-year", type=int, default=None, help="검색어 로테이션 위상 (검증용)"
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="ID,ID,...",
        help=(
            "지정한 세분류만 실행한다 (예: anxiety.restless,safety.crisis). "
            "소량으로 실제 API 응답을 먼저 확인할 때 쓴다. "
            "산출물은 videos.partial.json으로 나가며 배포 대상이 아니다."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="API를 호출하지 않고 전 과정을 검증한다"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def make_client(args: argparse.Namespace, tax: Taxonomy, budget: QuotaBudget) -> Client:
    if args.dry_run:
        logger.info("드라이런 — API를 호출하지 않는다 (쿼터 소모 0)")
        return DryRunClient(budget, tax.all_blocklist_terms)
    return YouTubeClient(os.environ.get("YOUTUBE_API_KEY", ""), budget)


def run(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    day_of_year = args.day_of_year if args.day_of_year is not None else now.timetuple().tm_yday

    tax = load_taxonomy(args.taxonomy)
    allowlist = load_allowlist(args.allowlist)
    previous = load_previous(args.previous)

    selected, run_crisis, only = resolve_selection(tax, args.only)
    if only is not None:
        logger.warning("=" * 68)
        logger.warning("부분 실행 — 지정된 %d개 항목만 처리한다: %s", len(only), ", ".join(only))
        logger.warning("산출물은 videos.partial.json이며 version.json을 만들지 않는다.")
        logger.warning("이 결과는 배포 대상이 아니다 (실제 API 응답 확인용).")
        if not run_crisis:
            logger.warning(
                "위기 카테고리를 건너뛰므로 일반 카테고리에서 위기 videoId를 제외하지 않는다."
            )
        logger.warning("=" * 68)

    logger.info(
        "세분류 %d/%d개 / 위기 %s / 화이트리스트 %d채널 (예시 %d건) / day_of_year=%d",
        len(selected),
        len(tax.subcategories),
        "실행" if run_crisis else "건너뜀",
        allowlist.size,
        len(allowlist.placeholders),
        day_of_year,
    )

    estimated = preflight(
        tax, allowlist, previous, day_of_year, args.hard_cap, selected, run_crisis
    )
    if estimated > args.hard_cap:
        logger.error(
            "예상 소모량 %d units가 하드캡 %d를 넘는다 — API를 호출하지 않고 중단한다",
            estimated,
            args.hard_cap,
        )
        return EXIT_QUOTA

    budget = QuotaBudget(hard_cap=args.hard_cap)
    ctx = BuildContext(
        tax=tax, client=make_client(args, tax, budget), budget=budget, previous=previous
    )
    _collect_allowlist_alerts(ctx, allowlist)

    # 1) 위기 카테고리 먼저 — 중단되더라도 안전 데이터는 갱신된 상태를 유지한다
    crisis = build_crisis(ctx, allowlist, now, day_of_year) if run_crisis else None
    crisis_age = check_crisis_freshness(ctx, crisis, now) if crisis else -1

    # 2) 일반 카테고리 — 위기 videoId를 후보에서 제외해 겹침을 원천 차단한다
    categories = build_categories(
        ctx, day_of_year, crisis.video_ids if crisis else set(), selected
    )

    # 3) 무결성 검증 후에만 기록한다
    assert_disjoint(categories, crisis)
    write_outputs(
        args.out_dir,
        _iso(now),
        categories,
        crisis,
        ctx,
        dry_run=args.dry_run,
        crisis_age_days=crisis_age,
        only=only,
    )

    print("\n".join(ctx.budget.report_lines()))
    _log_alert_summary(ctx)
    return EXIT_OK


def _collect_allowlist_alerts(ctx: BuildContext, allowlist: Allowlist) -> None:
    if allowlist.placeholders:
        logger.warning(
            "화이트리스트에 예시 항목 %d건이 남아 있어 건너뛴다", len(allowlist.placeholders)
        )
        ctx.collector.add(**alert_specs.allowlist_placeholders(len(allowlist.placeholders)))
    if allowlist.is_undersized:
        logger.warning(
            "화이트리스트 %d채널 < 최소 %d채널", allowlist.size, MIN_ALLOWLIST_SIZE
        )
        ctx.collector.add(
            **alert_specs.allowlist_undersized(allowlist.size, MIN_ALLOWLIST_SIZE)
        )


def _log_alert_summary(ctx: BuildContext) -> None:
    if not len(ctx.collector):
        logger.info("경보 없음")
        return
    logger.warning("경보 %d건:", len(ctx.collector))
    for alert in ctx.collector.alerts:
        logger.warning("  [%s] %s", alert.severity, alert.title)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return run(args)
    except QuotaExceeded as exc:
        logger.error("쿼터 중단: %s", exc)
        logger.error("부분 결과를 쓰지 않았다 — 직전 videos.json이 그대로 유지된다")
        return EXIT_QUOTA
    except SelectionError as exc:
        logger.error("%s", exc)
        return EXIT_RETRYABLE
    except (GuardrailError, IntegrityError) as exc:
        logger.error("안전 검증 실패: %s", exc)
        logger.error("배포하지 않는다")
        return EXIT_RETRYABLE
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 부분 결과를 남기지 않는다
        logger.exception("배치 실패: %s", exc)
        logger.error("부분 결과를 쓰지 않았다 — 직전 videos.json이 그대로 유지된다")
        return EXIT_RETRYABLE


def _setup_logging(verbose: bool) -> None:
    # Windows 콘솔(cp949)에서 한글·기호가 깨지지 않도록 UTF-8로 고정한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
