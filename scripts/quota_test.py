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

    print("-" * 84)
    if failures:
        print(f"{len(failures)}건 실패: {', '.join(failures)}")
        return EXIT_FAIL
    print(f"{len(CASES)}/{len(CASES)} 통과 + 예약 로직")
    return EXIT_OK


def check_reserve():
    """Actions 배치 예약이 언제 붙고 언제 풀리는지 고정한다.

    gh를 실제로 부르지 않는다 — 가짜 probe를 넣어 판정만 검사한다.
    CI(Actions)에서는 GITHUB_ACTIONS 때문에 예약이 애초에 0이고 probe도
    호출되지 않으므로, 이 테스트가 네트워크나 gh 설치에 의존하지 않는다.
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.quota_log import ACTIONS_BATCH_RESERVE, check as check_quota

    print()
    print("Actions 배치 예약 로직")
    print("-" * 84)

    saved = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "q.json"
            log.write_text(
                json.dumps({"2026-08-17": {"spent": 661, "runs": []}}), encoding="utf-8"
            )
            day = "2026-08-17"
            cases = [
                ("probe 없음 — 기존 동작", None, ACTIONS_BATCH_RESERVE),
                ("probe True — 배치 확인됨, 예약 해제", lambda d: True, 0),
                ("probe False — 그날 배치 없음, 예약 유지", lambda d: False, ACTIONS_BATCH_RESERVE),
                ("probe None — gh 확인 실패, 예약 유지", lambda d: None, ACTIONS_BATCH_RESERVE),
            ]
            for label, probe, want in cases:
                _, reserve = check_quota(
                    log, 661, day=day, batch_probe=probe, ceiling=99_999
                )
                ok = reserve == want
                print(f"{'   ' if ok else 'X  '}{label:<44} 예약 {reserve:>6,} (기대 {want:,})")
                if not ok:
                    yield label

            # probe에 넘어가는 날짜가 로그 키와 같아야 한다 (PT 기준)
            seen: list[str] = []
            check_quota(log, 1, day=day, batch_probe=lambda d: seen.append(d) or True,
                        ceiling=99_999)
            ok = seen == [day]
            print(f"{'   ' if ok else 'X  '}{'probe는 PT 날짜 키를 받는다':<44} {seen}")
            if not ok:
                yield "probe 날짜 키"
    finally:
        if saved is not None:
            os.environ["GITHUB_ACTIONS"] = saved


if __name__ == "__main__":
    raise SystemExit(main())
