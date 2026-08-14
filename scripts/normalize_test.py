# -*- coding: utf-8 -*-
"""정규화·분류 검증 스크립트.

    python scripts/normalize_test.py

띄어쓰기·반복문자·문장부호가 달라도 같은 세분류로 매칭되는지 확인하고,
**모든 대분류·세분류 label이 자기 이름만으로 매칭되는지**를 회귀 검사한다.

label 회귀 검사가 왜 있나
    "답답해"가 어디에도 매칭되지 않는 일이 있었다. taxonomy.yaml의 키워드가
    "가슴이답답"처럼 긴 구문만 담고 있어서, 대분류 이름인 "답답" 단독으로는
    걸리지 않았다. 사용자가 가장 먼저 떠올리는 말이 카테고리 이름 그 자체인데
    그게 안 걸리면 사전이 아무리 커도 소용이 없다.
    label 24 + 9개는 최소한의 바닥이므로 여기서 고정한다.

정규화는 lib.normalize를 그대로 쓴다 — 배치·앱·이 스크립트가 같은 구현을 봐야 한다.
(JS 쪽 동등성은 app/test/normalize.parity.test.js가 이 구현을 정답으로 삼아 검사한다)
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.normalize import normalize

ROOT = Path(__file__).resolve().parents[1]
tax = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))

EXIT_OK = 0
EXIT_FAIL = 1


def classify(text):
    """앱(classify.js)과 같은 순서로 판정한다: 위기 → 세분류 → 대분류 폴백."""
    n = normalize(text)
    if not n:
        return ("EMPTY", [])

    for kw in tax["safety"]["crisis_keywords"]:
        if normalize(kw) in n:
            return ("CRISIS", [kw])

    best = None
    for c in tax["categories"]:
        for s in c["subcategories"]:
            hits = [k for k in s["keywords"] if normalize(k) in n]
            if hits:
                score = (len(hits), sum(len(normalize(k)) for k in hits))
                if best is None or score > best[0]:
                    best = (score, s["id"], hits)
    if best:
        return (best[1], best[2])

    # 대분류 폴백 — 세분류를 특정하지 못하면 선택 UI로 넘어간다
    for c in tax["categories"]:
        hits = [k for k in (c.get("keywords") or []) if normalize(k) in n]
        if hits:
            return (f"{c['id']} (대분류→선택 UI)", hits)

    return (None, [])


def report(title, rows):
    print(f"\n{title}")
    print("-" * 76)
    for text, expect_match in rows:
        cid, hits = classify(text)
        ok = (cid is not None) if expect_match else True
        mark = "   " if ok else "X  "
        print(f"{mark}{text:<26} → {cid}  {hits[:3]}")
        if not ok:
            yield text


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    failures = []

    # --- 1) 정규화 형태 변형 ------------------------------------------------
    variants = [
        "마음이 급해 죽겠어",  # 띄어쓰기 있음
        "마음이급해죽겠어",  # 띄어쓰기 없음
        "마 음 이  급 해",  # 띄어쓰기 과다
        "짜증나아아아아!!!",  # 반복 + 문장부호
        "너무 외로워ㅠㅠㅠㅠ",
        "아무것도 하기 싫다...",
        "아무것도하기싫다",
        "발표 앞두고 너무 떨림",
        "요즘 계속 제자리인 것 같아",
        "그냥 다 놓고 싶어",
        "합격했어!!! 너무 뿌듯",
        "심심해 뭐하지",
    ]
    failures += list(report("형태 변형", [(v, True) for v in variants]))

    # --- 2) label 회귀: 세분류 24개 -----------------------------------------
    subs = [(s["label"], True) for c in tax["categories"] for s in c["subcategories"]]
    failures += list(report("세분류 label 단독 (24개)", subs))

    # --- 3) label 회귀: 대분류 9개 ------------------------------------------
    cats = [(c["label"], True) for c in tax["categories"]]
    failures += list(report("대분류 label 단독 (9개)", cats))

    # --- 4) label 활용형 ----------------------------------------------------
    conjugations = [
        "답답해", "답답하다", "답답한", "답답함", "답답하네요",
        "불안해", "불안하다", "불안한",
        "지루해", "지루하다",
        "외로워", "외로움", "외롭다",
        "즐거워", "즐거움",
        "슬퍼", "슬픔", "슬프다",
        "피로해", "피로가",
        "상실감이", "기쁨", "기뻐",
    ]
    failures += list(report("label 활용형", [(c, True) for c in conjugations]))

    # --- 5) 위기 검사가 감정보다 먼저인지 ------------------------------------
    print("\n위기 우선순위")
    print("-" * 76)
    for text in ["죽고싶다", "짜증나 짜증나 진짜 죽고싶어", "죽 고 싶", "자 해"]:
        cid, hits = classify(text)
        ok = cid == "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<26} → {cid}  {hits[:3]}")
        if not ok:
            failures.append(text)

    print("\n" + "=" * 76)
    if failures:
        print(f"실패 {len(failures)}건: {', '.join(failures)}")
        print("taxonomy.yaml의 keywords에 해당 어간을 추가하세요.")
        return EXIT_FAIL
    print("전부 통과")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
