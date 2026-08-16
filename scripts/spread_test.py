#!/usr/bin/env python
"""채널 분산 선정 검증 — 네트워크 호출 없음.

    python scripts/spread_test.py

일반 카테고리에 채널당 상한이 없던 시절의 실측 편중을 그대로 재현해 두고,
새 선정 로직이 그것을 억제하는지 확인한다. 드라이런으로는 검증되지 않는다 —
DryRunClient의 합성 데이터가 이미 12채널 균등이라 편중 상황 자체를 만들지 않는다.

고정해 두는 것
  1. 실측 편중이 이전 로직에서는 그대로 나온다 (전제가 살아 있는지)
  2. 새 로직이 그것을 상한 이하로 억제하면서 20건을 유지한다
  3. 상한 때문에 확보량이 줄어야 하는 상황에서만 사다리·해제가 작동한다
  4. 리팩터링이 위기 카테고리 선정 결과를 바꾸지 않았다 (안전 경로 회귀 방지)
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_videos import (
    _take_round_robin,
    select_category_videos,
    select_crisis_videos,
)
from lib.filters import Video
from lib.taxonomy import (
    CATEGORY_MAX_VIDEOS,
    CATEGORY_MIN_VIDEOS,
    CRISIS_MAX_VIDEOS,
    load_taxonomy,
)

ROOT = Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_FAIL = 0, 1

# 실측 편중 (배포된 videos.json에서 그대로 옮김)
#   2026-08-15 anger.rage           힐링포유 12/20, 나머지 8채널이 1건씩
#   2026-08-14 exhaustion.listless  소소한 일상 18/20
OBSERVED = [
    ("anger.rage", "2026-08-15", "힐링포유 Healing for you", 12),
    ("exhaustion.listless", "2026-08-14", "소소한 일상", 18),
]


def _video(video_id: str, channel: str) -> Video:
    return Video(
        video_id=video_id,
        title=f"{channel}의 영상 {video_id}",
        channel=channel,
        channel_id=f"UC_{channel}",
        published_at="2026-08-15T00:00:00Z",
        duration="PT10M",
        duration_seconds=600,
        description="",
        tags=(),
        comments_disabled=False,
    )


def _pool(spec: list[tuple[str, int]]) -> list[Video]:
    """(채널명, 건수) 목록을 순위 순서 그대로 후보 풀로 만든다.

    앞에 적은 채널이 순위 상위다 — 편중은 한 채널이 상위를 쓸어담아 생기므로
    그 형태를 그대로 만든다.
    """
    pool: list[Video] = []
    for channel, count in spec:
        for i in range(count):
            pool.append(_video(f"{channel}-{i}", channel))
    return pool


def _spread(picked: list[Video]) -> Counter:
    return Counter(v.channel for v in picked)


def _check(failures: list[str], ok: bool, label: str, detail: str = "") -> None:
    print(f"{'   ' if ok else 'X  '}{label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    failures: list[str] = []
    tax = load_taxonomy(ROOT / "taxonomy.yaml")
    ladder = tax.category_per_channel_ladder
    cap0 = ladder[0]
    print(f"일반 카테고리 상한 사다리: {list(ladder)}  (taxonomy.yaml category_selection)")

    # --- 1. 실측 편중을 재현하고 억제하는가 --------------------------------
    print("\n실측 편중 재현 → 억제")
    print("-" * 76)
    for cat, day, hog, hog_count in OBSERVED:
        # 편중 채널이 상위를 차지하고, 그 뒤로 1건짜리 채널들이 이어지는 형태.
        # 여유(surplus)는 실측이 카테고리당 100건 내외였으므로 넉넉히 둔다.
        others = [(f"채널{i}", 1) for i in range(40)]
        pool = _pool([(hog, hog_count), *others])

        old = pool[:CATEGORY_MAX_VIDEOS]  # 이전 로직 — 순위 상위를 그대로 자른다
        _check(
            failures,
            _spread(old)[hog] == hog_count,
            f"{cat} ({day}) 이전 로직에서 {hog} {hog_count}/20 재현",
            f"실제 {_spread(old)[hog]}건",
        )

        picked, cap, unlocked = select_category_videos(pool, ladder)
        spread = _spread(picked)
        _check(
            failures,
            spread[hog] <= cap0,
            f"{cat} 새 로직에서 {hog}가 상한 {cap0} 이하",
            f"{spread[hog]}건, {len(spread)}채널, 상한 {cap}{' 해제' if unlocked else ''}",
        )
        # 억제가 "제외"로 넘어가면 안 된다 — 관련성 1위 채널은 남아 있어야 한다.
        _check(
            failures,
            spread[hog] >= 1 and picked[0].channel == hog,
            f"{cat} 관련성 1위 영상은 목록 맨 앞에 그대로 남는다",
            f"1번={picked[0].channel}",
        )
        # 같은 채널이 목록에서 연달아 붙지 않는다 (보고된 증상: 썸네일 반복)
        adjacent = sum(
            1 for a, b in zip(picked, picked[1:]) if a.channel == b.channel
        )
        _check(
            failures,
            adjacent == 0,
            f"{cat} 같은 채널이 목록에서 서로 붙어 있지 않다",
            f"인접 {adjacent}쌍",
        )
        _check(
            failures,
            len(picked) == CATEGORY_MAX_VIDEOS,
            f"{cat} 20건을 그대로 채운다",
            f"{len(picked)}건",
        )
        _check(
            failures, not unlocked, f"{cat} 상한을 해제하지 않는다"
        )

    # --- 2. 채널 안의 순위 순서가 보존되는가 --------------------------------
    print("\n채널 내부 순서 보존")
    print("-" * 76)
    pool = _pool([(f"채널{i}", 5) for i in range(10)])
    picked, _, _ = select_category_videos(pool, ladder)
    order_ok = True
    for channel in {v.channel for v in picked}:
        ids = [v.video_id for v in picked if v.channel == channel]
        if ids != sorted(ids, key=lambda s: int(s.rsplit("-", 1)[1])):
            order_ok = False
    _check(failures, order_ok, "각 채널 안에서는 순위 순서가 유지된다")

    # --- 3. 사다리 — 채널이 모자라면 상한을 올린다 --------------------------
    print("\n사다리 (20건을 못 채울 때만 완화)")
    print("-" * 76)
    # 채널 5개 × 10건. 상한 3이면 15건뿐이라 20건에 미달 → 4(20건)에서 멈춘다.
    pool = _pool([(f"채널{i}", 10) for i in range(5)])
    picked, cap, unlocked = select_category_videos(pool, ladder)
    _check(
        failures,
        cap == 4 and len(picked) == CATEGORY_MAX_VIDEOS and not unlocked,
        "채널 5개 → 상한 4로 올려 20건 확보",
        f"상한 {cap}, {len(picked)}건, 해제 {unlocked}",
    )
    _check(
        failures,
        max(_spread(picked).values()) <= cap,
        "완화된 상한도 지켜진다",
        f"최다 {max(_spread(picked).values())}건",
    )

    # --- 4. 상한 해제 — 최소 확보량이 분산보다 우선 -------------------------
    print("\n상한 해제 (최소 확보량 15건 우선)")
    print("-" * 76)
    # 채널 2개 × 30건. 상한 5로도 10건뿐이라 15건 미달 → 해제하면 20건 채운다.
    pool = _pool([(f"채널{i}", 30) for i in range(2)])
    picked, cap, unlocked = select_category_videos(pool, ladder)
    _check(
        failures,
        unlocked and len(picked) == CATEGORY_MAX_VIDEOS,
        "채널 2개 → 상한을 해제하고 20건 확보",
        f"상한 {cap} 해제={unlocked}, {len(picked)}건",
    )

    # --- 5. 얕은 풀에서는 해제하지 않는다 -----------------------------------
    print("\n얕은 풀 (해제해도 늘지 않으면 하지 않는다)")
    print("-" * 76)
    # 채널 14개 × 1건 = 14건. 상한과 무관하게 14건이 전부다.
    pool = _pool([(f"채널{i}", 1) for i in range(14)])
    picked, cap, unlocked = select_category_videos(pool, ladder)
    _check(
        failures,
        not unlocked and len(picked) == 14,
        f"후보 14건(<{CATEGORY_MIN_VIDEOS}) — 상한 탓이 아니므로 해제하지 않는다",
        f"{len(picked)}건, 해제={unlocked}",
    )

    # --- 6. 일별 회전을 쓰지 않는다 (관련성 보존) ---------------------------
    print("\n회전 없음 — 관련성 상위 채널이 빠지지 않는다")
    print("-" * 76)
    # 실제 풀에 가까운 형태: 채널 61개로 슬롯 20개보다 3배 많다.
    # 위기용 회전을 그대로 가져오면 day마다 다른 20채널 '구간'을 자르게 되어
    # day 40이면 관련성 상위 40채널이 통째로 빠진다. 그래서 일반에는 쓰지 않는다.
    pool = _pool([("힐링포유", 12)] + [(f"채널{i:02d}", 2) for i in range(60)])
    order = list(dict.fromkeys(v.channel for v in pool))
    picked, _, _ = select_category_videos(pool, ladder)
    ranks = sorted(order.index(c) for c in _spread(picked))
    _check(
        failures,
        ranks == list(range(CATEGORY_MAX_VIDEOS)),
        "채널 61개 중 관련성 상위 20채널이 선정된다",
        f"채널순위 {ranks[0]}~{ranks[-1]}",
    )
    # 대조군 — 회전을 켜면 무슨 일이 일어나는지 고정해 둔다.
    # 이게 실패한다면 회전을 다시 켜도 된다는 뜻이므로 그때 재검토한다.
    rotated = _take_round_robin(
        pool, cap0, CATEGORY_MAX_VIDEOS, set(), day_of_year=40, rotate=True
    )
    rotated_ranks = sorted(order.index(v.channel) for v in {*rotated})
    _check(
        failures,
        "힐링포유" not in {v.channel for v in rotated},
        "(대조) 회전을 켜면 day 40에 관련성 1위 채널이 빠진다",
        f"회전 시 채널순위 {min(rotated_ranks)}~{max(rotated_ranks)}",
    )

    # --- 7. 위기 경로 불변 (리팩터링 회귀 방지) -----------------------------
    print("\n위기 카테고리 선정 (리팩터링 전후 동작이 같아야 한다)")
    print("-" * 76)
    crisis_ladder = tax.crisis_per_channel_ladder
    allow = {"UC_화이트A", "UC_화이트B", "UC_화이트C", "UC_화이트D",
             "UC_화이트E", "UC_화이트F", "UC_화이트G"}
    pool = _pool(
        [(f"화이트{c}", 5) for c in "ABCDEFG"] + [(f"검색{i}", 5) for i in range(5)]
    )
    picked, cap, unlocked = select_crisis_videos(pool, crisis_ladder, allow, day_of_year=0)
    spread = _spread(picked)
    _check(
        failures,
        len(picked) == CRISIS_MAX_VIDEOS,
        "위기 20건 확보",
        f"{len(picked)}건, 상한 {cap}",
    )
    _check(
        failures,
        max(spread.values()) <= crisis_ladder[0],
        f"위기 채널당 상한 {crisis_ladder[0]} 이하",
        f"최다 {max(spread.values())}건",
    )
    _check(
        failures,
        all(v.channel.startswith("화이트") for v in picked),
        "화이트리스트 채널만으로 20건이 차면 검색 채널은 들어오지 않는다",
        f"검색 채널 {sum(1 for v in picked if v.channel.startswith('검색'))}건",
    )

    print("\n" + "=" * 76)
    if failures:
        print(f"실패 {len(failures)}건:")
        for f in failures:
            print(f"  - {f}")
        return EXIT_FAIL
    print("전부 통과")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
