"""문자열 정규화 — 앱(JS)과 배치(Python)가 동일하게 구현해야 하는 규칙.

taxonomy.yaml `normalization.steps`가 단일 소스이며,
scripts/normalize_test.py의 구현과 문자 단위로 같은 결과를 낸다.

배치가 이 모듈을 쓰는 이유는 blocklist 매칭이다.
"죽 고 싶", "죽고싶ㅠㅠㅠ", "죽!고!싶!" 은 모두 같은 문자열로 접혀서
띄어쓰기·반복·문장부호를 이용한 우회를 막는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

# 공백·문장부호·이모지 제거. 한글 자모(ㄱ-ㅎ ㅏ-ㅣ)는 감정 표현이라 보존한다.
_NON_WORD = re.compile(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣa-z0-9]")

# 3회 이상 반복되는 문자를 2회로 축약 ("짜증나아아아" → "짜증나아")
_REPEATS = re.compile(r"(.)\1{2,}")


def normalize(text: str) -> str:
    """비교용 정규화 문자열을 반환한다."""
    if not text:
        return ""
    t = text.lower()
    t = _NON_WORD.sub("", t)
    t = _REPEATS.sub(r"\1\1", t)
    return t.replace("ㅜ", "ㅠ")


def matched_terms(haystack: str, terms: Iterable[str]) -> list[str]:
    """haystack(원문)에 포함된 terms를 정규화 기준으로 찾아 반환한다.

    걸러낸 이유를 로그·리포트에 남길 수 있도록 불리언이 아니라 목록을 준다.
    """
    normalized = normalize(haystack)
    if not normalized:
        return []
    hits: list[str] = []
    for term in terms:
        needle = normalize(term)
        if needle and needle in normalized:
            hits.append(term)
    return hits


def contains_any(haystack: str, terms: Sequence[str]) -> bool:
    """terms 중 하나라도 포함되면 True (단락 평가로 조기 종료)."""
    normalized = normalize(haystack)
    if not normalized:
        return False
    return any((needle := normalize(t)) and needle in normalized for t in terms)
