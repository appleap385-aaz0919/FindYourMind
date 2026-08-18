"""GitHub Actions 배치가 오늘 이미 돌았는지 확인한다 (YouTube 쿼터 소모 없음).

무엇에 쓰나 — 금액이 아니라 이름을 정한다
    로컬은 Actions의 쿼터 소모를 볼 수 없어서, quota_log는 배치 몫 7,900을
    하루 예산에서 항상 빼둔다. 그 7,900이 "예약"(앞으로 쓸 몫)인지
    "계상"(이미 쓴 몫)인지를 이 조회가 정한다.

    ⚠ **어느 쪽이든 금액은 같다.** 한때 "배치가 이미 돌았으면 예약을 푼다"로
    쓰였으나 2026-08-18에 되돌렸다 — 배치 소모는 로컬 로그에 없으므로
    예약을 풀면 그 7,900이 하루 회계에서 통째로 사라진다.
    검산 근거는 lib/quota_log.py의 check() 주석에 있다.

    그래도 이 조회가 필요한 이유: 운영자가 쿼터 표를 보고 "오늘 배치가
    돌았나"를 알 수 있어야 한다. gh는 이미 인증돼 있고 YouTube 쿼터를
    쓰지 않으므로 물어보는 비용이 0이다.

확인 실패는 이름만 잃는다
    gh가 없거나, 인증이 풀렸거나, 네트워크가 막혔거나, 응답이 이상하면
    None을 돌려준다. 호출자는 이름을 "배치 몫"으로 두고 금액은 그대로 뺀다.
    즉 조회 실패가 쿼터 판단을 바꾸지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.quota_log import pacific_date

DEFAULT_WORKFLOW = "build.yml"
DEFAULT_TIMEOUT = 15  # 초. 쿼터 판단 하나 때문에 오래 붙들려 있지 않는다.
LOOKBACK = 20  # 최근 실행 몇 건을 볼 것인가 (하루 1회 배치라 넉넉하다)

# PATH에서 못 찾았을 때 훑어볼 설치 경로.
#
#   왜 필요한가 (2026-08-18 실측)
#     gh가 설치돼 있고 Machine PATH에도 등록돼 있는데 shutil.which("gh")가
#     None이었다. 셸이 PATH 등록 이전의 환경을 물려받은 상태여서다.
#     이러면 probe가 영영 None을 돌려주고, "모르면 예약한다" 규칙에 따라
#     이미 돌아간 배치 몫 7,900이 계속 예약된 채로 남는다 —
#     ed6195d가 고치려던 바로 그 증상이 환경 문제로 되살아난다.
#
#   경로를 하드코딩하는 것이 마뜩잖지만, 대안은 사람이 GH_BIN을 매번
#   기억해서 넣는 것이다. 그건 이 프로젝트가 반복해서 실패한 방식이다.
#   찾지 못하면 종전처럼 "gh"를 돌려주므로 동작이 나빠지지는 않는다.
#
#   {}는 환경변수로 채운다. 값이 없으면 그 후보는 건너뛴다.
_GH_FALLBACKS: tuple[str, ...] = (
    # Windows — 기본 설치, winget, scoop, chocolatey
    r"{ProgramFiles}\GitHub CLI\gh.exe",
    r"{ProgramFiles(x86)}\GitHub CLI\gh.exe",
    r"{LOCALAPPDATA}\Programs\GitHub CLI\gh.exe",
    r"{USERPROFILE}\scoop\shims\gh.exe",
    r"{ProgramData}\chocolatey\bin\gh.exe",
    # macOS / Linux — homebrew(arm/intel), 패키지 매니저
    "/opt/homebrew/bin/gh",
    "/usr/local/bin/gh",
    "/usr/bin/gh",
)


def _gh_binary() -> str:
    """gh 실행 파일 경로.

    우선순위: GH_BIN(명시 지정) → PATH → 흔한 설치 경로.
    어디서도 못 찾으면 "gh"를 돌려준다. 그 경우 subprocess가 OSError를 내고
    호출자는 None(확인 실패)을 받는다 — 예약이 유지되는 안전한 방향이다.
    """
    explicit = os.environ.get("GH_BIN")
    if explicit:
        return explicit

    found = shutil.which("gh")
    if found:
        return found

    for template in _GH_FALLBACKS:
        try:
            candidate = template.format_map(os.environ)
        except KeyError:
            continue  # 그 환경변수가 없는 OS — 해당 없는 후보다
        if os.access(candidate, os.X_OK) and Path(candidate).is_file():
            return candidate

    return "gh"


def batch_succeeded_on(
    day: str,
    *,
    workflow: str = DEFAULT_WORKFLOW,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | None = None,
) -> bool | None:
    """PT 날짜 `day`에 배치가 성공했는가.

    True  — 성공한 실행이 있다 (예약을 풀어도 된다)
    False — 조회는 됐는데 그날 성공한 실행이 없다 (예약 유지)
    None  — 확인 실패. 알 수 없으므로 예약 유지.
    """
    cmd = [
        _gh_binary(), "run", "list",
        "--workflow", workflow,
        "--json", "createdAt,conclusion,status",
        "--limit", str(LOOKBACK),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, cwd=cwd, check=False
        )
    except (OSError, subprocess.SubprocessError):
        # gh 미설치·PATH 누락·타임아웃 — 전부 "모른다"로 처리한다.
        return None
    if proc.returncode != 0:
        return None  # 인증 만료, 저장소 밖에서 실행, 네트워크 오류 등

    try:
        runs = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(runs, list):
        return None

    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        stamp = run.get("createdAt")
        if not isinstance(stamp, str):
            continue
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if pacific_date(moment) == day:
            return True
    return False
