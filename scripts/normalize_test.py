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

    # --- 6) 자·타해 표현의 갈림 ----------------------------------------------
    #
    # "죽고싶"(위기)과 "죽여버리"(격분)는 정규화 후에도 부분 매칭되지 않는다.
    # 한글은 음절 단위라 "죽여버리고싶어"에서 죽 다음이 여이고 고가 아니기 때문이다.
    # 이 성질에 기대고 있으므로 여기서 고정한다 — 정규화 규칙이 바뀌면 여기서 걸린다.
    #
    # 방향이 갈리는 지점도 함께 고정한다. 타인 지향은 격분, 자기 지향은 위기다.
    # anger.rage에 "죽이고싶·없애버리고싶"을 넣으면서 자해 의사를 밝힌 입력이
    # 격분으로 분류되는 구멍이 생겼고(위기 키워드 어디에도 안 걸렸다),
    # safety.crisis_keywords의 자기 지향 가드가 그 구멍을 막는다.
    print("\n자·타해 표현의 갈림")
    print("-" * 76)
    if normalize("죽고싶") in normalize("죽여버리고 싶어"):
        print("X  '죽고싶'이 '죽여버리고 싶어'에 부분 매칭된다 — 정규화 규칙 확인 필요")
        failures.append("부분매칭")

    for text, expected in [
        ("죽고 싶어", "CRISIS"),
        ("죽여버리고 싶어", "anger.rage"),
        ("죽이고 싶어", "anger.rage"),
        ("패버리고 싶어", "anger.rage"),
        ("없애버리고 싶어", "anger.rage"),
        ("가만두지 않을거야", "anger.rage"),
        ("나를 죽이고 싶어", "CRISIS"),
        ("나 죽이고 싶어", "CRISIS"),
        ("나 죽여버리고 싶어", "CRISIS"),
        ("나를 없애버리고 싶어", "CRISIS"),
    ]:
        cid, hits = classify(text)
        ok = cid == expected
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid:<14} (기대 {expected})  {hits[:2]}")
        if not ok:
            failures.append(text)

    # --- 7) 활용형 흡수와 흔한 오타 -------------------------------------------
    #
    # 어간을 한 음절 더 줄여 활용형을 흡수한다. "미쳐버리"는 "미쳐버릴"을 잡지 못한다 —
    # 한글은 음절 단위라 리와 릴이 다른 글자다. "미쳐버"까지 줄이면 전부 걸린다.
    #
    # 다만 무조건 줄이면 안 된다. "미처버"는 "미처 버리지 못한 물건들"에도 걸리는데
    # 그건 상실감 맥락이라 격분으로 보내면 안 된다. 오타 쪽 어간은 좁게 잡았다.
    print("\n활용형과 오타")
    print("-" * 76)
    for text, expected in [
        ("미쳐버릴 것 같아", "anger.rage"),
        ("미쳐버리겠다", "anger.rage"),
        ("미쳐버려", "anger.rage"),
        ("미처버릴것같아", "anger.rage"),
        ("미쳐버리", "anger.rage"),
        ("미처버리", "anger.rage"),
        ("미처버리고싶어", "anger.rage"),
        # "미처버리"는 "미처 버리지 못한"에도 걸린다. sadness.loss의 "버리지못한"이
        # 더 길어 점수에서 이기므로 상실감 맥락은 그쪽으로 간다 — 길이 합 우선 규칙.
        ("미처 버리지 못한 물건들", "sadness.loss"),
        ("돌아버릴 것 같아", "anger.rage"),
        ("돌아버리겠다", "anger.rage"),
        ("환장하겠네", "anger.rage"),
        ("환장할 것 같아", "anger.rage"),
        ("귀찬아 죽겠어", "exhaustion.listless"),
        ("괜찬아졌어", "calm.stable"),
        ("빡처 죽겠네", "anger.irritation"),
        ("돼는일이없어", "frustration.blocked"),
        ("어떻하지", "anxiety.worry"),
    ]:
        cid, hits = classify(text)
        ok = cid == expected
        print(f"{'   ' if ok else 'X  '}{text:<22} → {cid:<22} (기대 {expected})  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 어간을 넓히다 격분으로 잘못 보내면 안 되는 표현들
    print("\n어간 오탐 방지")
    print("-" * 76)
    for text in ["뒤돌아 버렸다", "집에 돌아 버스를 탔다"]:
        cid, _ = classify(text)
        ok = cid != "anger.rage"
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}")
        if not ok:
            failures.append(text)

    # --- 8) 처지·쳐지·눅눅·터질 (2026-08-16 추가분) --------------------------
    #
    # 셋 다 "어간을 어디까지 줄일 것인가"가 결과를 가른 사례다.
    #
    #   처지 : 처지(處地)가 일상어라 2자로 줄이면 "내 처지가", "같은 처지라"가
    #          전부 걸린다(실측 오탐 11건). 활용형을 하나씩 적는 쪽을 택했다.
    #   눅눅 : 본래 용법이 물리적 습기라 주어를 고정하지 않으면 과자·빨래가 걸린다.
    #   터질 : **넓히는 것이 오히려 위험했던 사례다.** 이 사전은 매칭 수가 같으면
    #          키워드 길이 합으로 우선순위를 정하므로, "터질것같"(5자)을 넣으면
    #          기존의 올바른 짧은 키워드(웃음이·눈물이·속이터, 각 3자)를 전부
    #          이겨버린다. 2자로 두어야 그것들에 져서 제자리로 간다.
    #          아래 세 줄이 그 관계를 고정한다 — 어간을 늘리면 여기서 깨진다.
    print("\n처지·눅눅·터질 (어간 폭)")
    print("-" * 76)
    for text, expected in [
        # 목표 — 제보된 미분류 입력
        ("기분이 처진다", "sadness.sorrow"),
        ("기분이 쳐진다", "sadness.sorrow"),
        ("기분이 처져", "sadness.sorrow"),
        ("기분이 쳐져", "sadness.sorrow"),
        ("기분이 처지네", "sadness.sorrow"),
        ("기분이 눅눅해", "sadness.sorrow"),
        ("마음이 눅눅해", "sadness.sorrow"),
        ("눅눅한 기분이야", "sadness.sorrow"),
        ("터질거 같아", "frustration.suppressed"),
        ("터질 것 같아", "frustration.suppressed"),
        # "터질"이 기존 키워드를 이기면 안 된다 (길이 우선 규칙에 기대는 지점)
        ("웃음이 터질 것 같아", "joy.delight"),
        ("눈물이 터질 것 같아", "sadness.sorrow"),
        ("속이 터질 것 같아", "frustration.suppressed"),
        # "터질" 때문에 생긴 충돌을 막는 가드
        ("빵 터질 것 같아", "joy.delight"),
        ("대박 터질 것 같아", "flutter.anticipation"),
    ]:
        cid, hits = classify(text)
        ok = cid == expected
        print(f"{'   ' if ok else 'X  '}{text:<22} → {cid:<24} (기대 {expected})  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 처지/쳐지/눅눅을 2자로 줄이면 걸리는 일상 표현들.
    # 여기가 깨지면 어간이 넓어진 것이다 — 줄이지 말고 활용형을 늘려야 한다.
    print("\n어간 오탐 방지 (처지·쳐지·눅눅)")
    print("-" * 76)
    for text in [
        "내 처지가 딱해",
        "그 사람 처지도 이해돼",
        "처지를 바꿔서 생각해봐",
        "같은 처지라 그런지",
        "성적이 처지는 편이야",
        "관계가 고쳐지지 않아",
        "부딪쳐지는 일이 많아",
        "과자가 눅눅해졌어",
        "빨래가 눅눅해",
        "장마라 집이 눅눅해",
    ]:
        cid, hits = classify(text)
        ok = cid is None
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}  {hits[:2]}")
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
