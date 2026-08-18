#!/usr/bin/env python
"""쿼터 오류 판정 테스트 — 네트워크 호출 없음.

    python scripts/quota_test.py

왜 별도 테스트가 있나
    이 판정 하나가 "실패한 배치를 60초 뒤 재시도할지"를 결정한다.
    일일 쿼터가 소진된 상태에서 재시도하면 결과는 같고 시간만 버린다.
    반대로 분당 한도를 쿼터 소진으로 오판하면, 복구 가능한 실패에
    하루치 배치를 통째로 포기하게 된다.

    실제로 두 번 틀렸다:
      1. errors 배열 없이 error.status="RESOURCE_EXHAUSTED"만 오는 형태를 놓쳤다
      2. 일일 쿼터가 403이 아니라 429로 오는 경우를 놓쳤다 (실측)
    그래서 응답 형태를 표로 고정해 둔다. 새로운 형태를 만나면 여기에 한 줄 추가한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.quota import QuotaBudget, QuotaExceeded
from lib.youtube import YouTubeClient, YouTubeError

EXIT_OK = 0
EXIT_FAIL = 1

RETRYABLE = 1  # 종료 코드 1 — 워크플로가 60초 뒤 1회 재시도한다
QUOTA = 2  # 종료 코드 2 — 재시도하지 않는다

SVC = "of service 'youtube.googleapis.com'"


class FakeResponse:
    def __init__(self, status_code: int, body: Any, is_json: bool = True) -> None:
        self.status_code = status_code
        self._body = body
        self._is_json = is_json
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self) -> Any:
        if not self._is_json:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    def get(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        return self._response


def google_error(
    code: int,
    message: str | None = None,
    reasons: tuple[str, ...] = (),
    status: str | None = None,
) -> FakeResponse:
    error: dict[str, Any] = {"code": code}
    if message:
        error["message"] = message
    if reasons:
        error["errors"] = [{"reason": r} for r in reasons]
    if status:
        error["status"] = status
    return FakeResponse(code, {"error": error})


# (설명, 응답, 기대 종료 코드)
CASES: list[tuple[str, FakeResponse, int]] = [
    # --- 일일 쿼터 소진: 재시도하지 않는다 ---------------------------------
    (
        "429 일일 쿼터 (2026-08 실측)",
        google_error(
            429,
            "Quota exceeded for quota metric 'Search Queries' and limit "
            f"'Search Queries per day' {SVC}",
        ),
        QUOTA,
    ),
    ("403 quotaExceeded", google_error(403, reasons=("quotaExceeded",)), QUOTA),
    ("403 dailyLimitExceeded", google_error(403, reasons=("dailyLimitExceeded",)), QUOTA),
    (
        "403 RESOURCE_EXHAUSTED (errors 배열 없음)",
        google_error(403, "Quota exceeded", status="RESOURCE_EXHAUSTED"),
        QUOTA,
    ),
    (
        "403 일일 한도 메시지",
        google_error(403, f"...and limit 'Search Queries per day' {SVC}"),
        QUOTA,
    ),
    (
        "403 본문이 HTML인 쿼터 페이지",
        FakeResponse(403, "<html>Quota exceeded</html>", is_json=False),
        QUOTA,
    ),
    (
        "429 'per user per day' (사용자별 일일)",
        google_error(429, f"...and limit 'Queries per user per day' {SVC}"),
        QUOTA,
    ),
    (
        "429 reason은 rateLimit이지만 메시지가 per day",
        FakeResponse(
            429,
            {
                "error": {
                    "code": 429,
                    "message": f"...and limit 'Search Queries per day' {SVC}",
                    "errors": [{"reason": "rateLimitExceeded"}],
                }
            },
        ),
        QUOTA,
    ),
    # --- 단기 한도·기타 실패: 재시도 대상으로 남긴다 -------------------------
    (
        "429 분당 한도",
        google_error(429, f"...and limit 'Queries per minute per user' {SVC}"),
        RETRYABLE,
    ),
    (
        "429 100초 한도",
        google_error(429, f"...and limit 'Queries per 100 seconds per user' {SVC}"),
        RETRYABLE,
    ),
    ("429 창 정보 없음", google_error(429, "Too many requests"), RETRYABLE),
    (
        "429 quota만 언급, 창 불명 → 단기로 본다",
        google_error(429, "Quota exceeded for metric 'Queries'"),
        RETRYABLE,
    ),
    ("403 rateLimitExceeded", google_error(403, reasons=("rateLimitExceeded",)), RETRYABLE),
    (
        "403 분당 한도 메시지",
        google_error(403, f"...and limit 'Queries per minute' {SVC}"),
        RETRYABLE,
    ),
    ("403 keyInvalid", google_error(403, reasons=("keyInvalid",)), RETRYABLE),
    (
        "403 일반 Forbidden (쿼터 무관)",
        FakeResponse(403, "<html>403 Forbidden</html>", is_json=False),
        RETRYABLE,
    ),
    ("500 서버 오류", FakeResponse(500, {"error": {"code": 500}}), RETRYABLE),
    ("404", FakeResponse(404, {"error": {"code": 404}}), RETRYABLE),
]


def exit_code_for(response: FakeResponse) -> int:
    """이 응답을 만났을 때 build_videos.py가 낼 종료 코드."""
    client = YouTubeClient("test-key", QuotaBudget(hard_cap=99_999))
    client._session = FakeSession(response)  # noqa: SLF001 — 테스트 전용 주입
    try:
        client.videos(["x"])
    except QuotaExceeded:
        return QUOTA
    except YouTubeError:
        return RETRYABLE
    except Exception:  # noqa: BLE001
        return RETRYABLE
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print(f"{'응답 형태':<44}{'기대':>5}{'실제':>5}  {'':<5}동작")
    print("-" * 84)

    failures: list[str] = []
    for label, response, expected in CASES:
        actual = exit_code_for(response)
        ok = actual == expected
        if not ok:
            failures.append(label)
        action = "재시도 안 함" if actual == QUOTA else "60초 후 재시도"
        print(f"{label:<44}{expected:>5}{actual:>5}  {'OK  ' if ok else 'FAIL'} {action}")

    failures += list(check_reserve())
    failures += list(check_gh_lookup())

    print("-" * 84)
    if failures:
        print(f"{len(failures)}건 실패: {', '.join(failures)}")
        return EXIT_FAIL
    print(f"{len(CASES)}/{len(CASES)} 통과 + 배치 몫 회계 + gh 탐색")
    return EXIT_OK


def check_reserve():
    """Actions 배치 몫이 언제 붙고 언제 빠지는지 고정한다.

    가장 중요한 고정 (2026-08-18)
        **probe 결과가 금액을 바꾸지 않는다.** 배치가 이미 돌았어도 그 소모는
        로컬 로그에 없으므로 7,900은 그대로 예산에서 빠져야 한다. 예약을
        풀면 하루 회계에서 7,900이 통째로 사라진다 — 한때 그렇게 동작했고
        되돌렸다(근거는 lib/quota_log.py check() 주석).
        probe는 이름(예약/계상)만 정한다.

    gh를 실제로 부르지 않는다 — 가짜 probe를 넣어 판정만 검사한다.
    CI(Actions)에서는 GITHUB_ACTIONS 때문에 몫이 애초에 0이고 probe도
    호출되지 않으므로, 이 테스트가 네트워크나 gh 설치에 의존하지 않는다.
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.quota_log import ACTIONS_BATCH_RESERVE, check as check_quota

    print()
    print("Actions 배치 몫 — 금액과 이름")
    print("-" * 84)

    RESERVE = ACTIONS_BATCH_RESERVE
    saved = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "q.json"
            log.write_text(
                json.dumps({"2026-08-17": {"spent": 661, "runs": []}}), encoding="utf-8"
            )
            day = "2026-08-17"
            # (설명, probe, 기대 금액, 기대 이름)
            cases = [
                ("probe 없음 — 이름 미상, 금액 유지", None, RESERVE, "Actions 일일 배치 몫"),
                ("probe True — 이미 돌았다 → 계상 (금액 그대로)",
                 lambda d: True, RESERVE, "Actions 일일 배치 계상"),
                ("probe False — 아직 안 돌았다 → 예약",
                 lambda d: False, RESERVE, "Actions 일일 배치 예약"),
                ("probe None — 확인 실패, 금액 유지",
                 lambda d: None, RESERVE, "Actions 일일 배치 몫"),
            ]
            for label, probe, want_units, want_label in cases:
                _, allowance = check_quota(
                    log, 661, day=day, batch_probe=probe, ceiling=99_999
                )
                ok = allowance.units == want_units and allowance.label == want_label
                print(f"{'   ' if ok else 'X  '}{label:<48}"
                      f"{allowance.units:>7,}  {allowance.label}")
                if not ok:
                    print(f"{'':51}기대 {want_units:,}  {want_label}")
                    yield label

            # 로컬 로그에 전체 배치가 있으면 그 소모는 이미 spent에 있다 → 더하지 않는다.
            # 이것이 유일하게 금액이 0이 되는 경우다(Actions 내부·명시적 해제 제외).
            logged = Path(tmp) / "q2.json"
            logged.write_text(
                json.dumps({day: {"spent": 7914, "runs": [
                    {"script": "build_videos", "units": 7914, "only": None}
                ]}}),
                encoding="utf-8",
            )
            _, allowance = check_quota(
                logged, 1, day=day, batch_probe=lambda d: True, ceiling=99_999
            )
            ok = allowance.units == 0
            print(f"{'   ' if ok else 'X  '}"
                  f"{'로컬에 배치 기록 있음 → 0 (이중 계산 방지)':<48}{allowance.units:>7,}")
            if not ok:
                yield "had_full_batch 시 0"

            # probe에 넘어가는 날짜가 로그 키와 같아야 한다 (PT 기준)
            seen: list[str] = []
            check_quota(log, 1, day=day, batch_probe=lambda d: seen.append(d) or True,
                        ceiling=99_999)
            ok = seen == [day]
            print(f"{'   ' if ok else 'X  '}{'probe는 PT 날짜 키를 받는다':<48} {seen}")
            if not ok:
                yield "probe 날짜 키"

            # 회귀 방지의 핵심: 배치가 돌았다고 여유가 늘어나면 안 된다.
            # 되돌리기 전에는 여기서 여유가 7,900만큼 늘어났다.
            _, ran = check_quota(log, 0, day=day, batch_probe=lambda d: True,
                                 ceiling=9_500)
            _, not_ran = check_quota(log, 0, day=day, batch_probe=lambda d: False,
                                     ceiling=9_500)
            ok = ran.units == not_ran.units
            print(f"{'   ' if ok else 'X  '}"
                  f"{'배치 실행 여부가 여유를 바꾸지 않는다':<48}"
                  f"{ran.units:>7,} == {not_ran.units:,}")
            if not ok:
                yield "probe가 금액을 바꿈"
    finally:
        if saved is not None:
            os.environ["GITHUB_ACTIONS"] = saved


def check_gh_lookup():
    """gh 실행 파일을 어떤 순서로 찾는지 고정한다.

    실제 gh를 부르지 않는다 — 경로 결정만 검사하므로 gh 설치 여부와 무관하게
    Windows·Linux 어디서든 같은 결과가 나온다.

    이 테스트가 있는 이유 (2026-08-18)
        gh가 설치돼 있고 Machine PATH에도 있는데 shutil.which가 못 찾는
        환경이 실제로 있었다(셸이 낡은 환경을 물려받은 경우). 그러면 probe가
        영영 None을 돌려주고 배치 몫 7,900이 계속 예약된 채로 남는다.
        폴백 탐색이 조용히 사라지면 그 증상이 그대로 돌아온다.
    """
    import os
    import shutil
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib import actions_status

    print()
    print("gh 실행 파일 탐색 순서")
    print("-" * 84)

    saved_env = {k: os.environ.get(k) for k in ("GH_BIN", "FAKE_GH_HOME")}
    saved_which = shutil.which
    saved_fallbacks = actions_status._GH_FALLBACKS

    def restore() -> None:
        shutil.which = saved_which
        actions_status._GH_FALLBACKS = saved_fallbacks
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    try:
        with tempfile.TemporaryDirectory() as tmp:
            # 폴백이 실제로 집어야 할 "설치된 gh" 역할
            installed = Path(tmp) / ("gh.exe" if os.name == "nt" else "gh")
            installed.write_text("", encoding="utf-8")
            installed.chmod(0o755)
            os.environ["FAKE_GH_HOME"] = tmp
            actions_status._GH_FALLBACKS = (
                "{FAKE_GH_HOME}" + os.sep + installed.name,
                "{NO_SUCH_ENV_VAR_XYZ}" + os.sep + "gh",  # 없는 환경변수는 건너뛴다
            )

            cases = [
                (
                    "GH_BIN이 PATH보다 우선",
                    {"GH_BIN": "/explicit/gh"},
                    lambda _: "/from/path/gh",
                    "/explicit/gh",
                ),
                (
                    "GH_BIN 없으면 PATH를 쓴다",
                    {},
                    lambda _: "/from/path/gh",
                    "/from/path/gh",
                ),
                (
                    "PATH에 없으면 설치 경로를 훑는다",
                    {},
                    lambda _: None,
                    str(installed),
                ),
            ]
            for label, env, which_stub, want in cases:
                os.environ.pop("GH_BIN", None)
                os.environ.update(env)
                shutil.which = which_stub
                got = actions_status._gh_binary()
                ok = got == want
                print(f"{'   ' if ok else 'X  '}{label:<44} {got}")
                if not ok:
                    print(f"{'':47} 기대 {want}")
                    yield label

            # 어디에도 없으면 "gh" — subprocess가 OSError를 내고 probe는 None이 된다.
            # 즉 예약이 유지되는 안전한 방향으로 실패한다.
            os.environ.pop("GH_BIN", None)
            shutil.which = lambda _: None
            actions_status._GH_FALLBACKS = ("{NO_SUCH_ENV_VAR_XYZ}" + os.sep + "gh",)
            got = actions_status._gh_binary()
            ok = got == "gh"
            print(f"{'   ' if ok else 'X  '}{'아무 데도 없으면 gh (probe None → 이름만 미상)':<44} {got}")
            if not ok:
                yield "폴백 실패 시 기본값"
    finally:
        restore()


if __name__ == "__main__":
    raise SystemExit(main())
