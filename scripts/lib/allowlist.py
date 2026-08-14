"""channel_allowlist.yaml 로더.

위기 카테고리 가드레일 2의 데이터 소스다. 채널은 이 파일 한 곳에서만 관리하며,
변경은 PR로만 한다 (PLAN.md Phase 4.5 화이트리스트 관리 절차 1~2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# taxonomy.yaml auto_alerts / PLAN.md Phase 4.5에서 확정된 임계값
MIN_ALLOWLIST_SIZE = 15  # 이보다 줄면 풀 고갈 경고
REVIEW_OVERDUE_DAYS = 120  # last_reviewed_at 초과 시 재검토 Issue
NO_UPLOAD_DAYS = 90  # 최근 업로드가 없으면 Issue
MIN_BLOCKLIST_PASS_RATE = 0.5  # 통과율이 이보다 낮으면 채널 성향 변화 신호

# 스캐폴드에 들어 있는 예시 항목. 실제 채널로 교체될 때까지 배치가 건너뛴다.
PLACEHOLDER_PREFIX = "UC_EXAMPLE"

REQUIRED_FIELDS = (
    "channel_id",
    "channel_name",
    "added_at",
    "last_reviewed_at",
    "reviewed_by",
    "note",
)


class AllowlistError(ValueError):
    """channel_allowlist.yaml 구조 오류."""


@dataclass(frozen=True)
class AllowlistChannel:
    channel_id: str
    channel_name: str
    added_at: str
    last_reviewed_at: str
    reviewed_by: str
    note: str

    @property
    def is_placeholder(self) -> bool:
        return self.channel_id.startswith(PLACEHOLDER_PREFIX)

    def days_since_review(self, today: date) -> int | None:
        reviewed = _parse_date(self.last_reviewed_at)
        if reviewed is None:
            return None
        return (today - reviewed).days


@dataclass(frozen=True)
class Allowlist:
    channels: tuple[AllowlistChannel, ...]
    placeholders: tuple[AllowlistChannel, ...]
    path: Path

    @property
    def active_ids(self) -> tuple[str, ...]:
        return tuple(c.channel_id for c in self.channels)

    @property
    def size(self) -> int:
        return len(self.channels)

    @property
    def is_undersized(self) -> bool:
        return self.size < MIN_ALLOWLIST_SIZE


def load_allowlist(path: Path) -> Allowlist:
    """화이트리스트를 읽는다. 파일이 없으면 빈 목록으로 진행한다.

    파일 부재를 예외로 만들지 않는 이유: 위기 카테고리에는 전용 검색 fallback이 있어
    화이트리스트가 비어도 가드레일 1·3으로 안전이 유지된다. 대신 호출자가 경고를 낸다.
    """
    if not path.exists():
        return Allowlist(channels=(), placeholders=(), path=path)

    with path.open(encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    entries = raw.get("channels") or []
    if not isinstance(entries, list):
        raise AllowlistError(f"{path}: channels는 목록이어야 한다")

    active: list[AllowlistChannel] = []
    placeholders: list[AllowlistChannel] = []
    for index, entry in enumerate(entries):
        channel = _parse_channel(entry, index, path)
        (placeholders if channel.is_placeholder else active).append(channel)

    return Allowlist(
        channels=tuple(active), placeholders=tuple(placeholders), path=path
    )


def _parse_channel(entry: Any, index: int, path: Path) -> AllowlistChannel:
    if not isinstance(entry, dict):
        raise AllowlistError(f"{path}: channels[{index}]가 매핑이 아니다")
    missing = [f for f in REQUIRED_FIELDS if not str(entry.get(f, "")).strip()]
    if missing:
        raise AllowlistError(
            f"{path}: channels[{index}]({entry.get('channel_id', '?')})에 "
            f"필수 필드 누락 — {', '.join(missing)}. "
            "taxonomy.yaml required_fields_per_channel 참조."
        )
    return AllowlistChannel(
        channel_id=str(entry["channel_id"]).strip(),
        channel_name=str(entry["channel_name"]).strip(),
        added_at=str(entry["added_at"]).strip(),
        last_reviewed_at=str(entry["last_reviewed_at"]).strip(),
        reviewed_by=str(entry["reviewed_by"]).strip(),
        note=str(entry["note"]).strip(),
    )


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
