"""일일 쿼터 소모 기록 — 같은 날 두 번 돌려 한도를 넘기는 사고를 막는다.

왜 필요한가
    실행 전 산정(QuotaEstimate)은 "이번 실행이 얼마를 쓸까"만 본다.
    그날 이미 얼마를 썼는지는 모르기 때문에, 배치를 한 번 돌린 뒤 부분 실행을
    두어 번 더 하면 매번 "여유 있습니다"라고 하면서 한도를 넘긴다.
    실제로 그렇게 소진돼 429를 받았다(2026-08-14).

날짜 키는 **태평양 시간 기준**이다
    쿼터는 PT 자정에 리셋된다. 로컬 날짜로 키를 잡으면 리셋 전후가 뒤섞인다.
    한국 시간 오전에는 PT로 아직 전날이라, KST 날짜를 쓰면 이미 쓴 양을
    "오늘"이 아닌 것으로 착각해 그대로 한도를 넘게 된다.

기록 파일은 커밋하지 않는다 (.gitignore)
    기기마다 값이 다르고, 커밋하면 매 실행이 워킹트리를 더럽힌다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG = ".quota_log.json"

# 하루 한도 10,000에서 이만큼 아래를 실행 상한으로 둔다.
# 하드캡(9,800)은 "이번 실행 하나"의 상한이고, 이건 "그날 전체"의 상한이다.
DAILY_CEILING = 9_500

# GitHub Actions 일일 배치가 쓰는 양 (scripts/lib/quota.py 예산표).
# 로컬은 Actions의 소모를 볼 수 없으므로, 배치가 돌 것으로 가정하고 미리 비워둔다.
ACTIONS_BATCH_RESERVE = 7_900

# 보관 기간. 오래된 기록은 자동으로 지운다 — 진단용이지 회계 장부가 아니다.
KEEP_DAYS = 30


class QuotaBudgetExceeded(RuntimeError):
    """그날 누적 + 이번 예상이 상한을 넘는다. API를 호출하지 않고 중단한다."""


def pacific_date(now: datetime | None = None) -> str:
    """쿼터 리셋 기준(태평양 시간)의 날짜 키를 반환한다."""
    moment = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001 — tzdata가 없는 환경(일부 Windows/슬림 컨테이너)
        # PST 고정으로 근사한다. 서머타임 기간에는 경계가 1시간 어긋나지만,
        # 날짜가 통째로 밀리는 것보다 훨씬 낫다.
        return (moment.astimezone(timezone.utc) - timedelta(hours=8)).date().isoformat()


@dataclass(frozen=True)
class DayUsage:
    date: str
    spent: int
    runs: tuple[dict[str, Any], ...]

    @property
    def had_full_batch(self) -> bool:
        """그날 전체 배치(--only 없는 build_videos)가 이미 기록됐는가."""
        return any(
            r.get("script") == "build_videos" and not r.get("only") for r in self.runs
        )


def read_day(path: Path, day: str | None = None) -> DayUsage:
    day = day or pacific_date()
    data = _load(path)
    entry = data.get(day) or {}
    runs = tuple(entry.get("runs") or ())
    return DayUsage(date=day, spent=int(entry.get("spent") or 0), runs=runs)


def record(
    path: Path,
    *,
    script: str,
    units: int,
    exit_code: int,
    only: list[str] | None = None,
    dry_run: bool = False,
    day: str | None = None,
) -> DayUsage:
    """실제 소모량을 누적한다.

    실패한 실행도 기록한다 — 중단 전까지 부른 호출은 이미 쿼터를 썼다.
    드라이런은 0 units이므로 누적에 영향이 없지만, 무엇을 돌렸는지는 남긴다.
    """
    day = day or pacific_date()
    data = _load(path)
    entry = data.setdefault(day, {"spent": 0, "runs": []})
    entry["spent"] = int(entry.get("spent") or 0) + int(units)
    entry["runs"].append(
        {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script": script,
            "units": int(units),
            "exit": int(exit_code),
            "only": only,
            "dry_run": dry_run,
            "source": "actions" if os.environ.get("GITHUB_ACTIONS") else "local",
        }
    )
    _prune(data)
    _save(path, data)
    return read_day(path, day)


def check(
    path: Path,
    estimate: int,
    *,
    ceiling: int = DAILY_CEILING,
    reserve_actions_batch: bool = True,
    day: str | None = None,
) -> tuple[DayUsage, int]:
    """실행해도 되는지 판단한다. 넘으면 QuotaBudgetExceeded를 던진다.

    반환: (그날 사용량, 적용된 예약분)
    """
    usage = read_day(path, day)

    # 예약은 "로컬 실행이 Actions 배치 몫을 까먹지 않도록" 비워두는 장치다.
    # 그래서 두 경우에는 적용하지 않는다:
    #   - Actions 안에서 도는 중이면 — 자기 자신을 위해 자리를 비울 이유가 없다.
    #     (러너는 매번 초기화되므로 누적도 0이라, 예약까지 걸면 배치가 스스로를 거부한다)
    #   - 오늘 전체 배치가 이미 기록됐으면 — 예약분이 실제 소모로 바뀌었다.
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    reserve = (
        ACTIONS_BATCH_RESERVE
        if reserve_actions_batch and not usage.had_full_batch and not in_actions
        else 0
    )
    projected = usage.spent + estimate + reserve
    if projected > ceiling:
        raise QuotaBudgetExceeded(
            f"오늘(PT {usage.date}) 누적 {usage.spent:,} + 이번 예상 {estimate:,}"
            + (f" + Actions 배치 예약 {reserve:,}" if reserve else "")
            + f" = {projected:,} > 상한 {ceiling:,}. API를 호출하지 않고 중단한다."
        )
    return usage, reserve


def table(usage: DayUsage, estimate: int, reserve: int, ceiling: int) -> str:
    lines = [
        "",
        f"오늘 쿼터 현황 (PT {usage.date} 기준 — 리셋은 태평양 자정)",
        "=" * 64,
        f"  {'그날 누적 소모':<30}{usage.spent:>12,}",
        f"  {'이번 실행 예상':<30}{estimate:>12,}",
    ]
    if reserve:
        lines.append(f"  {'Actions 일일 배치 예약':<30}{reserve:>12,}")
    total = usage.spent + estimate + reserve
    lines += [
        "-" * 64,
        f"  {'합계':<30}{total:>12,}",
        f"  일일 상한 {ceiling:,} → 여유 {ceiling - total:,} units",
        "=" * 64,
    ]
    if usage.runs:
        lines.append("  오늘 실행 내역:")
        for run in usage.runs[-5:]:
            scope = ",".join(run["only"]) if run.get("only") else "전체"
            lines.append(
                f"    {run['at'][11:16]}  {run['script']:<16}{run['units']:>7,} units"
                f"  [{run.get('source', '?')}] {scope}"
            )
        lines.append("=" * 64)
    return "\n".join(lines)


# --- 파일 입출력 -------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 기록이 깨졌다고 배치를 막지는 않는다. 빈 상태로 다시 시작한다.
        return {}
    return data if isinstance(data, dict) else {}


def _save(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # 기록 실패로 배치를 죽이지 않는다. 기록은 보조 장치다.
        pass


def _prune(data: dict[str, Any]) -> None:
    if len(data) <= KEEP_DAYS:
        return
    for old in sorted(data)[: len(data) - KEEP_DAYS]:
        data.pop(old, None)
