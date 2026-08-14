"""자동 경보 — 사람이 잊어도 시스템이 먼저 말한다.

build_videos.py와 check_channels.py가 판정만 하고, Issue 생성은 워크플로가 한다
(판정 로직과 GitHub 의존성을 분리해 로컬에서도 그대로 검증할 수 있게).

taxonomy.yaml auto_alerts 5종 + PLAN.md에서 추가된 위기 신선도 경보를 모두 여기서 만든다.
title은 워크플로의 중복 Issue 판정 키이므로 같은 사유는 항상 같은 문자열이어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["critical", "warning", "info"]

# 이미 열려 있는 Issue를 다시 찔러야 하는 주기.
# 워크플로에 하드코딩하지 않고 경보 정의에 담아, 정책이 이 파일 한 곳에만 있게 한다.
DEFAULT_RENOTIFY_DAYS = 7

# 안전 관련 경보는 더 자주 찌른다.
# crisis_stale이 3일에 발동하는데 재알림이 7일이면, 위기 풀이 계속 낡아가는 상태를
# 주 1회만 알리게 된다. 감지 주기보다 알림 주기가 길면 경보의 의미가 없다.
SAFETY_RENOTIFY_DAYS = 2

# 안전 장치가 아예 없는 상태는 매일 알린다.
# 위기 영상 0건은 "풀이 낡았다"가 아니라 "안전 장치가 없다"는 뜻이다.
CRITICAL_RENOTIFY_DAYS = 1


@dataclass(frozen=True)
class Alert:
    type: str
    severity: Severity
    title: str
    body: str
    labels: tuple[str, ...] = ()
    renotify_days: int = DEFAULT_RENOTIFY_DAYS

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "labels": list(self.labels),
            "renotify_days": self.renotify_days,
        }


@dataclass
class AlertCollector:
    alerts: list[Alert] = field(default_factory=list)

    def add(
        self,
        *,
        type: str,
        severity: Severity,
        title: str,
        body: str,
        labels: tuple[str, ...] = (),
        renotify_days: int = DEFAULT_RENOTIFY_DAYS,
    ) -> None:
        self.alerts.append(
            Alert(
                type=type,
                severity=severity,
                title=title,
                body=body,
                labels=labels,
                renotify_days=renotify_days,
            )
        )

    def to_json(self) -> list[dict[str, Any]]:
        return [a.to_json() for a in self.alerts]

    def __len__(self) -> int:
        return len(self.alerts)

    @property
    def has_critical(self) -> bool:
        return any(a.severity == "critical" for a in self.alerts)


# --- 경보 생성기 (문구를 한곳에 모아 Issue 제목이 흔들리지 않게 한다) -----------


def channel_dead(channel_id: str, name: str) -> dict[str, Any]:
    return {
        "type": "channel_dead",
        "severity": "critical",
        "title": f"[화이트리스트] 채널 접근 불가: {name} ({channel_id})",
        "body": (
            f"채널 `{channel_id}` ({name}) 이(가) API 응답에 없습니다. "
            "삭제·비공개·차단 가능성이 있습니다.\n\n"
            "조치: 채널 상태를 확인하고 `channel_allowlist.yaml`에서 제외하거나 교체하세요 (PR 필수)."
        ),
        "labels": ("allowlist", "auto"),
    }


def channel_stale_uploads(channel_id: str, name: str, days: int | None) -> dict[str, Any]:
    days_text = f"{days}일" if days is not None else "확인 불가"
    return {
        "type": "channel_stale_uploads",
        "severity": "warning",
        "title": f"[화이트리스트] 90일 무업로드: {name} ({channel_id})",
        "body": (
            f"채널 `{channel_id}` ({name}) 의 마지막 업로드가 {days_text} 전입니다.\n\n"
            "조치: 활동이 멈춘 채널이면 교체를 검토하세요. 풀 신선도에 영향을 줍니다."
        ),
        "labels": ("allowlist", "auto"),
    }


def channel_low_pass_rate(
    channel_id: str, name: str, rate: float, checked: int
) -> dict[str, Any]:
    return {
        "type": "channel_low_pass_rate",
        "severity": "critical",
        "title": f"[화이트리스트] blocklist 통과율 저하: {name} ({channel_id})",
        "body": (
            f"채널 `{channel_id}` ({name}) 의 최근 영상 {checked}건 중 "
            f"blocklist 통과율이 {rate:.0%}입니다 (기준 50%).\n\n"
            "채널 성향이 변했을 수 있습니다. 최근 업로드를 직접 확인하고 "
            "부적합하면 화이트리스트에서 제외하세요."
        ),
        "labels": ("allowlist", "safety", "auto"),
    }


def channel_review_overdue(channel_id: str, name: str, days: int) -> dict[str, Any]:
    return {
        "type": "channel_review_overdue",
        "severity": "warning",
        "title": f"[화이트리스트] 재검토 기한 초과: {name} ({channel_id})",
        "body": (
            f"`last_reviewed_at` 이후 {days}일이 지났습니다 (기준 120일).\n\n"
            "조치: 채널 최근 영상 성향을 확인한 뒤 `last_reviewed_at`과 `reviewed_by`를 "
            "갱신하세요 (PR 필수)."
        ),
        "labels": ("allowlist", "auto"),
    }


def allowlist_undersized(size: int, minimum: int) -> dict[str, Any]:
    return {
        "type": "allowlist_undersized",
        "severity": "critical",
        "title": f"[화이트리스트] 채널 수 부족 ({size}/{minimum})",
        "body": (
            f"활성 채널이 {size}개로 최소 기준 {minimum}개를 밑돕니다.\n\n"
            "위기 카테고리의 영상 풀이 고갈될 수 있습니다. "
            "taxonomy.yaml `selection_criteria`에 맞는 채널을 보충하세요."
        ),
        "labels": ("allowlist", "safety", "auto"),
        "renotify_days": SAFETY_RENOTIFY_DAYS,
    }


def crisis_carried_over(kept: int, minimum: int) -> dict[str, Any]:
    return {
        "type": "crisis_carried_over",
        "severity": "critical",
        "title": "[위기 카테고리] 확보량 미달 — 직전 결과 유지",
        "body": (
            f"필터 통과 영상이 {kept}건으로 최소 {minimum}건에 미달했습니다.\n\n"
            "규칙대로 필터를 완화하지 않고 직전 배치 결과를 유지했습니다. "
            "`crisis.updated_at`이 갱신되지 않으므로 신선도 경보가 이어질 수 있습니다.\n\n"
            "조치: 화이트리스트 채널 상태와 blocklist 용어 과다 여부를 확인하세요."
        ),
        "labels": ("safety", "auto"),
    }


def crisis_stale(updated_at: str, days: int, threshold: int) -> dict[str, Any]:
    return {
        "type": "crisis_stale",
        "severity": "critical",
        "title": "[위기 카테고리] 풀이 갱신되지 않음",
        "body": (
            f"`crisis.updated_at`이 {updated_at}로 {days}일째 갱신되지 않았습니다 "
            f"(기준 {threshold}일).\n\n"
            "직전 결과 유지 규칙이 반복 발동 중입니다. 화이트리스트 보충이 필요합니다."
        ),
        "labels": ("safety", "auto"),
        "renotify_days": SAFETY_RENOTIFY_DAYS,
    }


def crisis_empty() -> dict[str, Any]:
    return {
        "type": "crisis_empty",
        "severity": "critical",
        "title": "[위기 카테고리] 영상 0건 — 상담 안내만 노출됨",
        "body": (
            "필터를 통과한 영상이 없고 유지할 직전 결과도 없어 위기 카테고리 영상이 "
            "비어 있습니다.\n\n"
            "앱은 상담 안내만 표시합니다(의도된 안전 동작). "
            "화이트리스트를 채워 정상화하세요."
        ),
        "labels": ("safety", "auto"),
        "renotify_days": CRITICAL_RENOTIFY_DAYS,
    }


def category_low_yield(category_id: str, count: int, minimum: int) -> dict[str, Any]:
    return {
        "type": "category_low_yield",
        "severity": "warning",
        "title": f"[배치] 카테고리 확보량 미달: {category_id}",
        "body": (
            f"`{category_id}` 확보 영상이 {count}건으로 목표 하한 {minimum}건에 미달합니다.\n\n"
            "검색어 적합성 또는 필터 과다 여부를 확인하세요."
        ),
        "labels": ("batch", "auto"),
    }


def category_overfiltered(category_id: str, ratio: float, detail: str) -> dict[str, Any]:
    return {
        "type": "category_overfiltered",
        "severity": "warning",
        "title": f"[배치] blocklist 과다 필터링: {category_id}",
        "body": (
            f"`{category_id}`에서 blocklist가 후보의 {ratio:.0%}를 제거했습니다 (기준 50%).\n\n"
            f"계층별 제거 건수: {detail}\n\n"
            "용어가 과도한지, 검색어가 부적절한지 사람이 판단해야 합니다."
        ),
        "labels": ("batch", "auto"),
    }


def allowlist_placeholders(count: int) -> dict[str, Any]:
    return {
        "type": "allowlist_placeholders",
        "severity": "warning",
        "title": f"[화이트리스트] 예시 항목이 남아 있음 ({count}건)",
        "body": (
            f"`channel_allowlist.yaml`에 스캐폴드 예시 항목이 {count}건 남아 있어 "
            "배치가 건너뛰었습니다.\n\n"
            "실제 채널로 교체하세요."
        ),
        "labels": ("allowlist", "auto"),
    }
