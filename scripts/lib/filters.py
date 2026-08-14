"""영상 필터 — videos.list 응답을 검증하고 걸러낸다.

필터 순서에는 이유가 있다.
    1) 이용 불가(삭제·비공개·처리 중)  ← 애초에 노출 자체가 불가능
    2) 국내 차단
    3) 3분 미만 (Shorts 포함)
    4) blocklist 계층 — 제목만 검사한다 (blocklist_text 참조)
정확한 길이 판정은 search.list의 videoDuration 파라미터가 아니라
videos.list의 contentDetails.duration으로 한다.
videoDuration=medium은 4분 이상이라 3~4분 영상을 놓치고,
medium+long을 따로 부르면 search 비용이 2배(100 units씩)가 되기 때문이다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lib.normalize import matched_terms

_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)

_SHORTS_MARKERS = ("#shorts", "#short", "#쇼츠")

KOREA_REGION = "KR"


def blocklist_text(snippet: Mapping[str, Any]) -> str:
    """blocklist 매칭 대상 텍스트를 뽑는다 — **제목만** 본다.

    설명란과 태그를 보지 않는 이유:
        설명란에는 해시태그·링크·채널 소개·타임스탬프·상담 안내가 뒤섞여 있다.
        blocklist를 여기까지 적용하면 영상 내용과 무관한 문자열에 걸린다.
        특히 자살예방 상담전화를 성실히 적어둔 채널이 tier_a의 "자살"에 잡혀
        제외되는, 정책 의도와 정반대의 결과가 구조적으로 발생한다.
        태그는 애초에 사용자에게 보이지 않는 필드라 노출 판단 근거가 될 수 없다.

    제목만으로 충분한 이유:
        사용자가 실제로 읽고 클릭 여부를 정하는 건 제목(과 썸네일)이다.
        썸네일은 어차피 자동으로 볼 수 없어 사람 검토(OPERATIONS.md)에 맡긴다.

    snippet을 그대로 받는 이유:
        배치(filters)·후보 수집(suggest_channels)·채널 점검(check_channels)이
        같은 규칙을 쓰도록 매칭 범위를 이 함수 한 곳에만 둔다.
    """
    return str(snippet.get("title", ""))


@dataclass(frozen=True)
class Video:
    """videos.json에 실릴 영상 1건 (+ 필터 판단에 쓰는 부가 정보)."""

    video_id: str
    title: str
    channel: str
    channel_id: str
    published_at: str
    duration: str
    duration_seconds: int
    description: str
    tags: tuple[str, ...]
    comments_disabled: bool

    def to_json(self) -> dict[str, str]:
        """PLAN.md 4절 스키마 그대로. 썸네일 URL은 videoId로 조립하므로 넣지 않는다."""
        return {
            "videoId": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "publishedAt": self.published_at,
            "duration": self.duration,
        }

    @property
    def blocklist_text(self) -> str:
        """blocklist를 적용할 대상: 제목만 (filter_rules). 근거는 blocklist_text() 참조."""
        return blocklist_text({"title": self.title})

    @property
    def shorts_marker_text(self) -> str:
        """Shorts 표기 탐지 대상: 제목 + 설명 + 태그.

        blocklist와 달리 여기서는 설명·태그를 계속 본다.
        #shorts는 업로더가 형식을 스스로 밝힌 표기라 오탐 여지가 없고,
        제목에는 안 붙이고 설명에만 넣는 채널이 흔하다.
        """
        return " ".join((self.title, self.description, " ".join(self.tags)))


@dataclass
class FilterStats:
    """단계별 제거 건수. 과다 필터링을 사람이 판단할 수 있게 남긴다."""

    considered: int = 0
    dropped_unavailable: int = 0
    dropped_region: int = 0
    dropped_short: int = 0
    dropped_shorts_tag: int = 0
    entered_blocklist: int = 0
    dropped_by_tier: Counter[str] = field(default_factory=Counter)
    samples: list[str] = field(default_factory=list)
    kept: int = 0

    @property
    def dropped_blocklist(self) -> int:
        return sum(self.dropped_by_tier.values())

    @property
    def blocklist_drop_ratio(self) -> float:
        if self.entered_blocklist <= 0:
            return 0.0
        return self.dropped_blocklist / self.entered_blocklist

    def is_overfiltered(self, threshold: float = 0.5) -> bool:
        """blocklist 단계에서 절반 이상이 잘려나갔는가.

        taxonomy.yaml blocklist_tiers.logging의 "확보량 50% 이상 감소" 경고 조건.
        """
        return self.entered_blocklist > 0 and self.blocklist_drop_ratio >= threshold

    def summary(self) -> str:
        tiers = ", ".join(f"{k}:{v}" for k, v in sorted(self.dropped_by_tier.items())) or "0"
        return (
            f"후보 {self.considered} → 확보 {self.kept} "
            f"(이용불가 {self.dropped_unavailable}, 국내차단 {self.dropped_region}, "
            f"3분미만 {self.dropped_short}, Shorts표기 {self.dropped_shorts_tag}, "
            f"blocklist {self.dropped_blocklist} [{tiers}])"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "kept": self.kept,
            "dropped_unavailable": self.dropped_unavailable,
            "dropped_region": self.dropped_region,
            "dropped_short": self.dropped_short,
            "dropped_shorts_tag": self.dropped_shorts_tag,
            "dropped_blocklist": self.dropped_blocklist,
            "dropped_by_tier": dict(self.dropped_by_tier),
            "blocklist_drop_ratio": round(self.blocklist_drop_ratio, 3),
            "blocked_samples": self.samples[:5],
        }


def parse_duration(iso: str) -> int:
    """ISO 8601 duration → 초. 파싱 실패는 0을 반환해 '3분 미만'으로 걸러지게 한다."""
    if not iso:
        return 0
    match = _DURATION.match(iso)
    if not match:
        return 0
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def build_video(item: Mapping[str, Any]) -> Video | None:
    """videos.list 항목 → Video. 노출 불가 상태면 None."""
    status = item.get("status") or {}
    if status.get("privacyStatus") != "public":
        return None
    if status.get("uploadStatus") not in (None, "processed"):
        return None

    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    stats = item.get("statistics") or {}
    duration = str(content.get("duration", ""))

    return Video(
        video_id=str(item.get("id", "")),
        title=str(snippet.get("title", "")),
        channel=str(snippet.get("channelTitle", "")),
        channel_id=str(snippet.get("channelId", "")),
        published_at=str(snippet.get("publishedAt", "")),
        duration=duration,
        duration_seconds=parse_duration(duration),
        description=str(snippet.get("description", "")),
        tags=tuple(str(t) for t in (snippet.get("tags") or [])),
        # commentCount가 없으면 댓글 사용 중지로 본다.
        # filter_rules의 "댓글 사용 중지된 영상 우선"은 제외가 아니라 정렬 가중치다.
        comments_disabled="commentCount" not in stats,
    )


def _is_region_blocked(item: Mapping[str, Any]) -> bool:
    restriction = (item.get("contentDetails") or {}).get("regionRestriction") or {}
    blocked = restriction.get("blocked") or []
    allowed = restriction.get("allowed")
    if KOREA_REGION in blocked:
        return True
    return bool(allowed) and KOREA_REGION not in allowed


def _has_shorts_marker(video: Video) -> bool:
    text = video.shorts_marker_text.lower()
    return any(marker in text for marker in _SHORTS_MARKERS)


def apply_filters(
    items: Iterable[Mapping[str, Any]],
    tiers: Mapping[str, Sequence[str]],
    *,
    min_seconds: int,
) -> tuple[list[Video], FilterStats]:
    """videos.list 응답에 필터를 적용한다.

    tiers는 적용할 blocklist 계층만 담는다 (긍정 감정 카테고리는 tier_a만).
    걸러낸 건수는 계층별로 나누어 세서 어떤 층이 과하게 잡는지 볼 수 있게 한다.
    """
    stats = FilterStats()
    kept: list[Video] = []

    for item in items:
        stats.considered += 1

        video = build_video(item)
        if video is None:
            stats.dropped_unavailable += 1
            continue
        if _is_region_blocked(item):
            stats.dropped_region += 1
            continue
        if video.duration_seconds < min_seconds:
            stats.dropped_short += 1
            continue
        if _has_shorts_marker(video):
            stats.dropped_shorts_tag += 1
            continue

        stats.entered_blocklist += 1
        blocked_tier, hits = _blocklist_verdict(video, tiers)
        if blocked_tier:
            stats.dropped_by_tier[blocked_tier] += 1
            if len(stats.samples) < 20:
                stats.samples.append(f"[{blocked_tier}] {video.title} ← {', '.join(hits)}")
            continue

        kept.append(video)

    stats.kept = len(kept)
    return kept, stats


def _blocklist_verdict(
    video: Video, tiers: Mapping[str, Sequence[str]]
) -> tuple[str | None, list[str]]:
    text = video.blocklist_text
    for tier_name, terms in tiers.items():
        hits = matched_terms(text, terms)
        if hits:
            return tier_name, hits
    return None, []


def dedupe(video_ids: Iterable[str]) -> list[str]:
    """순서(검색 관련도)를 보존하며 중복 videoId를 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for vid in video_ids:
        if vid and vid not in seen:
            seen.add(vid)
            ordered.append(vid)
    return ordered
