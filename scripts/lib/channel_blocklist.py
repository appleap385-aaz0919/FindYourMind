"""channel_blocklist.yaml 로더 — 채널 단위 차단 목록.

channel_allowlist.py와 대칭이지만 적용 범위가 반대다.
    화이트리스트  위기 카테고리에만. "이 채널만 쓴다"
    블록리스트    일반 + 위기 전부에. "이 채널은 쓰지 않는다"

제목 blocklist로 잡히지 않는 유형(막장 서사 낭독 등)을 위한 안전망이다.
근본 방어선은 검색어 설계이며, 이 목록이 빠르게 길어지면 검색어를 먼저 본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = ("channel_id", "channel_name", "added_at", "added_by", "reason")


class ChannelBlocklistError(ValueError):
    """channel_blocklist.yaml 구조 오류."""


@dataclass(frozen=True)
class BlockedChannel:
    channel_id: str
    channel_name: str
    added_at: str
    added_by: str
    reason: str


@dataclass(frozen=True)
class ChannelBlocklist:
    channels: tuple[BlockedChannel, ...]
    path: Path

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(c.channel_id for c in self.channels)

    @property
    def by_id(self) -> dict[str, BlockedChannel]:
        return {c.channel_id: c for c in self.channels}

    @property
    def size(self) -> int:
        return len(self.channels)


def load_channel_blocklist(path: Path) -> ChannelBlocklist:
    """차단 목록을 읽는다. 파일이 없으면 빈 목록으로 진행한다.

    파일 부재를 예외로 만들지 않는 이유: 이 목록은 안전망이지 필수 장치가 아니다.
    없다고 배치를 세우면, 정작 필요한 blocklist·길이 필터까지 함께 멈춘다.
    """
    if not path.exists():
        return ChannelBlocklist(channels=(), path=path)

    with path.open(encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    entries = raw.get("channels") or []
    if not isinstance(entries, list):
        raise ChannelBlocklistError(f"{path}: channels는 목록이어야 한다")

    channels: list[BlockedChannel] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ChannelBlocklistError(f"{path}: channels[{index}]가 매핑이 아니다")
        missing = [f for f in REQUIRED_FIELDS if not str(entry.get(f, "")).strip()]
        if missing:
            raise ChannelBlocklistError(
                f"{path}: channels[{index}]({entry.get('channel_id', '?')})에 "
                f"필수 필드 누락 — {', '.join(missing)}"
            )
        channels.append(
            BlockedChannel(
                channel_id=str(entry["channel_id"]).strip(),
                channel_name=str(entry["channel_name"]).strip(),
                added_at=str(entry["added_at"]).strip(),
                added_by=str(entry["added_by"]).strip(),
                reason=" ".join(str(entry["reason"]).split()),
            )
        )
    return ChannelBlocklist(channels=tuple(channels), path=path)
