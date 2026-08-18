# -*- coding: utf-8 -*-
"""감정 분류 — app/src/lib/classify.js의 Python 대응 구현.

왜 두 구현이 있나
    배치·검증 스크립트는 Python이고 앱은 JS다. 같은 taxonomy를 같은 규칙으로
    읽어야 하므로 알고리즘이 양쪽에 있다. normalize도 같은 사정이다.

⚠ 두 구현이 갈리면 조용히 어긋난다
    2026-08-18 이전에는 이 알고리즘이 normalize_test.py와 coverage_test.py에
    **각자 복사되어** 있었다. 사전을 고칠 때 검증은 Python 사본으로 하는데
    사용자가 보는 것은 classify.js라, JS가 바뀌어도 Python 테스트는 자기 사본을
    검사하며 통과한다. 구현을 여기 하나로 모으고
    app/test/classify.parity.test.js가 JS와 대조하도록 했다.
    (normalize가 이미 같은 방식으로 묶여 있다 — normalize.parity.test.js)

    규칙을 고칠 일이 있으면 **여기와 classify.js를 함께** 고치고
    픽스처를 다시 만든다: node test/gen-classify-fixture.mjs

규칙 (taxonomy.yaml normalization.matching)
    1. 위기 검사가 항상 먼저다. 감정 점수 계산에 닿기 전에 반환한다.
    2. 세분류: (매칭된 키워드 수, 키워드 길이 합) 순으로 최상위를 고른다.
    3. 무매칭이면 대분류 keywords로 폴백한다 — 세분류는 사용자가 고른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.normalize import normalize

CRISIS = "crisis"
OK = "ok"
CATEGORY = "category"
NO_MATCH = "nomatch"
EMPTY = "empty"


@dataclass(frozen=True)
class Outcome:
    """분류 결과. kind는 classify.js의 RESULT와 같은 값을 쓴다."""

    kind: str
    category_id: str | None = None
    subcategory_id: str | None = None
    hits: tuple[str, ...] = field(default=())


def classify(text: str, taxonomy: dict) -> Outcome:
    """정규화된 입력을 taxonomy에 대고 분류한다.

    인자 순서를 classify.js와 같게 둔다 — classify(text, taxonomy).
    """
    normalized = normalize(text)
    if not normalized:
        return Outcome(kind=EMPTY)

    # --- 위기 검사: 무조건 먼저 -------------------------------------------
    for keyword in taxonomy["safety"]["crisis_keywords"]:
        needle = normalize(keyword)
        if needle and needle in normalized:
            return Outcome(kind=CRISIS, hits=(keyword,))

    best = _best_subcategory(normalized, taxonomy)
    if best:
        _, category_id, subcategory_id, hits = best
        return Outcome(
            kind=OK,
            category_id=category_id,
            subcategory_id=subcategory_id,
            hits=tuple(hits),
        )

    # --- 대분류 폴백 -------------------------------------------------------
    fallback = _best_category(normalized, taxonomy)
    if fallback:
        _, category_id, hits = fallback
        return Outcome(kind=CATEGORY, category_id=category_id, hits=tuple(hits))

    return Outcome(kind=NO_MATCH)


def _score(hits: list[str]) -> tuple[int, int]:
    """(매칭 수, 길이 합). 길이 합이 두 번째 항인 이유는 taxonomy 주석 참조."""
    return len(hits), sum(len(normalize(k)) for k in hits)


def _best_subcategory(normalized: str, taxonomy: dict):
    best = None
    for category in taxonomy["categories"]:
        for subcategory in category["subcategories"]:
            hits = [
                k for k in subcategory["keywords"]
                if normalize(k) and normalize(k) in normalized
            ]
            if not hits:
                continue
            score = _score(hits)
            if best is None or score > best[0]:
                best = (score, category["id"], subcategory["id"], hits)
    return best


def _best_category(normalized: str, taxonomy: dict):
    best = None
    for category in taxonomy["categories"]:
        hits = [
            k for k in (category.get("keywords") or [])
            if normalize(k) and normalize(k) in normalized
        ]
        if not hits:
            continue
        score = _score(hits)
        if best is None or score > best[0]:
            best = (score, category["id"], hits)
    return best
