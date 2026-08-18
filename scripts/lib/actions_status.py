"""GitHub Actions 배치가 오늘 이미 돌았는지 확인한다 (YouTube 쿼터 소모 없음).

왜 필요한가
    로컬은 Actions의 쿼터 소모를 볼 수 없어서, quota_log는 배치 몫 7,900을
    미리 예약해 둔다. 그런데 그 판단은 로컬 기록만 보므로 Actions 배치는
    영원히 "아직 안 돌았다"로 남는다. 결과적으로 **이미 돌아간 배치 몫을
    한 번 더 예약**한다.

    배치는 매일 UTC 08:30(KST 17:30)에 돌고 쿼터일은 PT 자정에 바뀌므로,
    KST 17:30부터 다음 날 16:00까지 하루의 대부분이 이 상태다.
    그 시간대에는 실제로 2,000 가까이 남아 있는데도 로컬 실행이 거부될 수 있다.

    gh CLI는 이미 인증돼 있고 YouTube 쿼터를 쓰지 않으므로, 그날 배치가
    성공했는지 물어보고 성공했으면 예약을 푼다.

안전 원칙 — 모르면 예약한다
    gh가 없거나, 인증이 풀렸거나, 네트워크가 막혔거나, 응답이 이상하면
    None을 돌려준다. 호출자는 None을 "확인 실패"로 보고 예약을 유지한다.
    쿼터를 이중으로 태우는 것보다 한 번 덜 도는 쪽이 낫다.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from lib.quota_log import pacific_date

DEFAULT_WORKFLOW = "build.yml"
DEFAULT_TIMEOUT = 15  # 초. 쿼터 판단 하나 때문에 오래 붙들려 있지 않는다.
LOOKBACK = 20  # 최근 실행 몇 건을 볼 것인가 (하루 1회 배치라 넉넉하다)


def _gh_binary() -> str:
    """gh 실행 파일. PATH에 없으면 GH_BIN으로 지정할 수 있다."""
    return os.environ.get("GH_BIN") or "gh"


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
