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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG = ".quota_log.json"

# 하루 한도 10,000에서 이만큼 아래를 실행 상한으로 둔다.
# 하드캡(9,800)은 "이번 실행 하나"의 상한이고, 이건 "그날 전체"의 상한이다.
DAILY_CEILING = 9_500

# GitHub Actions 일일 배치가 쓰는 양 (scripts/lib/quota.py 예산표).
# 로컬은 Actions의 소모를 볼 수 없으므로, 이 양을 하루 예산에서 항상 빼둔다.
#
# 배치가 아직 안 돌았으면 "예약"(앞으로 쓸 몫), 이미 돌았으면 "계상"(이미 쓴 몫)이다.
# **이름만 다르고 금액은 같다** — 아래 [2026-08-18 검산] 참조.
ACTIONS_BATCH_RESERVE = 7_900

# 보관 기간. 오래된 기록은 자동으로 지운다 — 진단용이지 회계 장부가 아니다.
KEEP_DAYS = 30


class QuotaBudgetExceeded(RuntimeError):
    """그날 누적 + 이번 예상이 상한을 넘는다. API를 호출하지 않고 중단한다."""


@dataclass(frozen=True)
class BatchAllowance:
    """Actions 일일 배치 몫을 하루 회계에 어떻게 반영하는가.

    units      — 하루 예산에서 뺄 양. 0이면 반영하지 않는다.
    already_ran — 그날 배치가 이미 돌았는가 (batch_probe의 답).
                  True  → "계상" (이미 쓴 몫. 로컬 로그에 없으므로 여기서 더한다)
                  False → "예약" (앞으로 쓸 몫. 미리 비워둔다)
                  None  → 확인 실패. 어느 쪽인지 모른다.
                  **셋 다 금액은 같다.** 이 값은 표시용이지 금액을 바꾸지 않는다.
    """

    units: int
    already_ran: bool | None = None

    def __bool__(self) -> bool:
        return bool(self.units)

    @property
    def label(self) -> str:
        if self.already_ran is True:
            return "Actions 일일 배치 계상"
        if self.already_ran is False:
            return "Actions 일일 배치 예약"
        return "Actions 일일 배치 몫"


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
    batch_probe: Callable[[str], bool | None] | None = None,
) -> tuple[DayUsage, BatchAllowance]:
    """실행해도 되는지 판단한다. 넘으면 QuotaBudgetExceeded를 던진다.

    batch_probe는 "그 PT 날짜에 Actions 배치가 성공했는가"를 답하는 함수다
    (lib.actions_status.batch_succeeded_on). 그 답은 배치 몫을 "예약"으로 부를지
    "계상"으로 부를지만 정한다 — **금액은 어느 쪽이든 같다.**
    넘기지 않으면 조회하지 않는다.

    반환: (그날 사용량, 적용된 배치 몫 BatchAllowance)
    """
    usage = read_day(path, day)

    # ==================================================================
    # [2026-08-18 검산] 배치 몫은 배치가 돈 뒤에도 예산에서 빠져야 한다
    # ==================================================================
    #   2026-08-18: 이 계산이 이중 예약처럼 보였으나 검산해보니 정확했다.
    #   배치 소모는 로컬 로그에 없으므로 예약분을 계상해야 하루 회계가 맞는다.
    #
    #   ed6195d는 "배치가 이미 돌았으면 예약을 푼다"로 고쳤다가 되돌렸다.
    #   그때 근거로 삼은 수치를 다시 계산하면 전제가 어긋나 있었다:
    #
    #     PT 2026-08-17 실측
    #       Actions 배치      7,914   ← 로컬 로그에 없다 (러너는 휘발성)
    #       로컬 suggest_ch.  1,362
    #       실제 소진         9,276  →  진짜 잔량 약 724
    #
    #       예약 유지  1,362 + 7,900 = 9,262  여유  238  ← 724 - 안전마진 500 과 일치
    #       예약 해제  1,362 +     0 = 1,362  여유 8,138  ← 약 7,400 과다
    #
    #   "여유 278이면 다음 실행이 거부된다, 실제로는 2,000 가까이 남았는데"가
    #   ed6195d의 근거였는데, 2,086은 **배치 직후** 잔량이고 그 시점엔 로컬
    #   1,322를 이미 쓴 뒤였다. 두 시점을 겹쳐 읽은 것이다.
    #   여유 278은 오류가 아니라 정확한 값이었다.
    #
    #   가르는 기준은 "배치가 돌았는가"가 아니라 **"그 소모가 usage.spent에
    #   들어 있는가"** 다. 배치는 앞으로 쓰든 이미 썼든 같은 날 예산을 먹는다.
    #
    # 그래서 세 경우에만 적용하지 않는다:
    #   - Actions 안에서 도는 중이면 — 이 실행이 곧 배치다. 자기 자신을 위해
    #     자리를 비우면 배치가 스스로를 거부한다 (러너 누적은 0에서 시작).
    #   - 오늘 전체 배치가 **로컬에 기록**됐으면 — 그 소모가 이미 usage.spent에
    #     있다. 여기서 또 더하면 그때야말로 진짜 이중 계산이다.
    #   - 호출자가 --no-reserve-actions-batch로 명시적으로 뺐으면.
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    applies = reserve_actions_batch and not usage.had_full_batch and not in_actions

    # probe는 금액이 아니라 이름을 정한다 — 예약(미실행)인가 계상(실행 완료)인가.
    # 운영자가 표를 보고 "오늘 배치가 돌았나"를 알 수 있게 하는 것이 목적이다.
    # 확인에 실패하면(None) 이름만 모를 뿐 금액은 그대로다.
    already_ran = batch_probe(usage.date) if (applies and batch_probe) else None

    allowance = BatchAllowance(
        units=ACTIONS_BATCH_RESERVE if applies else 0,
        already_ran=already_ran,
    )
    projected = usage.spent + estimate + allowance.units
    if projected > ceiling:
        raise QuotaBudgetExceeded(
            f"오늘(PT {usage.date}) 누적 {usage.spent:,} + 이번 예상 {estimate:,}"
            + (f" + {allowance.label} {allowance.units:,}" if allowance else "")
            + f" = {projected:,} > 상한 {ceiling:,}. API를 호출하지 않고 중단한다."
        )
    return usage, allowance


def table(usage: DayUsage, estimate: int, reserve: BatchAllowance, ceiling: int) -> str:
    lines = [
        "",
        f"오늘 쿼터 현황 (PT {usage.date} 기준 — 리셋은 태평양 자정)",
        "=" * 64,
        f"  {'그날 누적 소모':<30}{usage.spent:>12,}",
        f"  {'이번 실행 예상':<30}{estimate:>12,}",
    ]
    if reserve:
        # "계상"으로 나오면 그날 배치는 이미 돌았다는 뜻이다 (금액은 예약과 같다).
        lines.append(f"  {reserve.label:<30}{reserve.units:>12,}")
    total = usage.spent + estimate + reserve.units
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
