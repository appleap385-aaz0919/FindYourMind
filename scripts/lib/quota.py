"""YouTube Data API v3 쿼터 회계.

[비용표] https://developers.google.com/youtube/v3/determine_quota_cost
    search.list         100 units   ← 이것만 비싸다. 호출 횟수가 곧 비용이다.
    videos.list           1 unit    (id를 50개까지 묶어 1회 호출)
    channels.list         1 unit    (id를 50개까지 묶어 1회 호출)
    playlistItems.list    1 unit    (재생목록 1개당 1회 호출)

[일일 한도] 10,000 units — 태평양 시간 자정에 리셋된다.
    그래서 워크플로 cron은 PT 자정 직후로 잡는다(.github/workflows/build.yml 참조).

[하루 예산 — PLAN.md Phase 1 확정치]
    일반 24 세분류 × 쿼리 3개(4개 중 3개 로테이션) × 100  = 7,200
    위기 전용 검색 6개 × 100                              =   600
    위기 화이트리스트 channels.list 1 + playlistItems 20   =    21
    영상 검증 videos.list (후보 약 4,400개 / 50개씩)       =    88
    ------------------------------------------------------------
    build_videos.py 합계                                  ≈ 7,909
    check_channels.py                                     ≈    25
    ------------------------------------------------------------
    총합                                                  ≈ 7,934  (하드캡 9,800 이내)

[초기 계산이 틀렸던 이유 — 재발 방지용 기록]
    최초 추정 9,600(24×4×100)은 위기 카테고리 600, 영상 검증, 채널 헬스체크를
    모두 누락한 값이었다. 전량 실행 시 실제로는 약 10,358로 한도를 넘는다.
    그래서 쿼리 3/4 로테이션을 도입했다.

[하지 말 것]
    search.list(channelId=...)로 화이트리스트 채널을 뒤지면 채널당 100 units다.
    25채널이면 2,500 units로 예산이 붕괴한다.
    channels.list → uploads 재생목록 → playlistItems.list 경로는 채널당 1 unit이고,
    결과도 "그 채널의 최신 업로드"라 검색보다 정확하다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

DAILY_LIMIT = 10_000

# 한도 10,000을 그대로 쓰지 않는다. 수동 재실행·검증 여유분 200을 남긴다.
DEFAULT_HARD_CAP = 9_800

COST: dict[str, int] = {
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
}


class QuotaExceeded(RuntimeError):
    """쿼터 하드캡 초과.

    재시도해도 같은 결과이므로 워크플로는 이 예외로 끝난 실행을 재시도하지 않는다
    (build_videos.py는 종료 코드 2로 구분해 알린다).
    """


@dataclass
class QuotaBudget:
    """실행 중 실제 소모량을 세고, 하드캡을 넘으려는 호출을 미리 막는다."""

    hard_cap: int = DEFAULT_HARD_CAP
    spent: int = 0
    calls: Counter[str] = field(default_factory=Counter)

    def charge(self, endpoint: str, calls: int = 1) -> None:
        """호출 직전에 비용을 청구한다. 넘치면 호출하지 않고 예외를 던진다."""
        if endpoint not in COST:
            raise KeyError(f"비용표에 없는 엔드포인트: {endpoint}")
        cost = COST[endpoint] * calls
        if self.spent + cost > self.hard_cap:
            raise QuotaExceeded(
                f"하드캡 {self.hard_cap:,} 초과 — 현재 {self.spent:,} + "
                f"{endpoint} {cost:,} = {self.spent + cost:,}. "
                "부분 결과를 쓰지 않고 중단한다."
            )
        self.spent += cost
        self.calls[endpoint] += calls

    @property
    def remaining(self) -> int:
        return max(0, self.hard_cap - self.spent)

    def report_lines(self) -> list[str]:
        lines = ["실제 소모 쿼터", "-" * 52]
        for endpoint, count in sorted(self.calls.items()):
            units = COST[endpoint] * count
            lines.append(f"  {endpoint:<20} {count:>5}회  {units:>6,} units")
        lines.append("-" * 52)
        lines.append(
            f"  {'합계':<20} {'':>5}    {self.spent:>6,} units "
            f"(하드캡 {self.hard_cap:,}, 잔여 {self.remaining:,})"
        )
        return lines


@dataclass(frozen=True)
class QuotaEstimate:
    """실행 전 예상 소모량. 하드캡을 넘으면 API를 한 번도 부르지 않고 중단한다."""

    rows: tuple[tuple[str, str, int, int], ...]  # (항목, 엔드포인트, 호출 수, units)

    @property
    def total(self) -> int:
        return sum(row[3] for row in self.rows)

    def table(self, hard_cap: int) -> str:
        lines = ["", "예상 쿼터 소모량 (실행 전 산정)", "=" * 64]
        lines.append(f"  {'항목':<30}{'호출':>8}{'units':>12}")
        lines.append("-" * 64)
        for label, _endpoint, calls, units in self.rows:
            lines.append(f"  {label:<30}{calls:>8,}{units:>12,}")
        lines.append("-" * 64)
        margin = hard_cap - self.total
        verdict = "OK" if margin >= 0 else "초과 — 중단"
        lines.append(f"  {'합계':<30}{'':>8}{self.total:>12,}")
        lines.append(
            f"  하드캡 {hard_cap:,} / 일일 한도 {DAILY_LIMIT:,} "
            f"→ 여유 {margin:,} units [{verdict}]"
        )
        lines.append("=" * 64)
        return "\n".join(lines)


def build_estimate(
    *,
    category_search_calls: int,
    crisis_search_calls: int,
    allowlist_channels: int,
    expected_video_ids: int,
) -> QuotaEstimate:
    """호출 계획으로부터 예상 소모량 표를 만든다 (보수적 상한 기준)."""
    videos_calls = -(-expected_video_ids // 50)  # 올림 나눗셈
    channels_calls = -(-allowlist_channels // 50) if allowlist_channels else 0
    rows = (
        (
            "일반 카테고리 검색",
            "search.list",
            category_search_calls,
            category_search_calls * COST["search.list"],
        ),
        (
            "위기 전용 검색",
            "search.list",
            crisis_search_calls,
            crisis_search_calls * COST["search.list"],
        ),
        (
            "화이트리스트 채널 조회",
            "channels.list",
            channels_calls,
            channels_calls * COST["channels.list"],
        ),
        (
            "화이트리스트 업로드 조회",
            "playlistItems.list",
            allowlist_channels,
            allowlist_channels * COST["playlistItems.list"],
        ),
        (
            "영상 검증 (삭제·비공개·길이)",
            "videos.list",
            videos_calls,
            videos_calls * COST["videos.list"],
        ),
    )
    return QuotaEstimate(rows=rows)
