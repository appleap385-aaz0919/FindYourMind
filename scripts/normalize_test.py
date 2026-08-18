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

    # --- 9) 사전 일괄 보강 (2026-08-16) --------------------------------------
    #
    # 세분류당 30~57개로 늘리면서 제보분을 함께 넣었다.
    # 여기 있는 것은 "이 표현이 이 세분류로 가야 한다"는 약속이다.
    print("\n일괄 보강 — 제보분")
    print("-" * 76)
    for text, expected in [
        ("힘들어", "exhaustion.tired"),
        ("너무 힘들다", "exhaustion.tired"),
        ("오늘 진짜 힘드네", "exhaustion.tired"),
        ("싸우고 싶어", "anger.rage"),
        ("도망치고 싶어", "exhaustion.burnout"),
        ("도망가고 싶다", "exhaustion.burnout"),
        ("헛헛하다", "sadness.lonely"),
        ("이해되지 않아", "frustration.stuck"),
        ("이해가 안 돼", "frustration.stuck"),
    ]:
        cid, hits = classify(text)
        ok = cid == expected
        print(f"{'   ' if ok else 'X  '}{text:<22} → {cid:<24} (기대 {expected})  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 욕설은 감정 표현으로 매우 흔하다. 어간이 일상어를 삼키지 않는지가 관건이라
    # 잡혀야 하는 것과 잡히면 안 되는 것을 나란히 둔다.
    print("\n일괄 보강 — 욕설 (전부 anger.irritation)")
    print("-" * 76)
    for text in ["씨발", "시발 진짜", "ㅅㅂ", "좆같아", "좇같아", "개같네", "개같은 경우",
                 "개빡친다", "존나 짜증나", "꼴받네"]:
        cid, hits = classify(text)
        ok = cid == "anger.irritation"
        print(f"{'   ' if ok else 'X  '}{text:<22} → {cid}  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 욕설 어간이 삼키면 안 되는 것들 — 개같이(속담)/존나(강조어)
    #
    # "시발"은 시발점·시발역을 삼키는 걸 알면서 넣었다. 씨/시 표기 혼동이
    # 처/쳐만큼 흔한데 "시발"을 빼면 절반을 놓치고, 시발점·시발역은 감정 입력
    # 상자에 적힐 말이 아니다. 반대로 "개같이"(속담)와 "존나"(강조어)는
    # 일상 대화에 그대로 나오므로 어간을 좁혀 피했다.
    print("\n일괄 보강 — 욕설 어간 오탐 방지")
    print("-" * 76)
    for text in ["개같이 벌어서 정승같이 쓴다", "존나 좋아", "존나 맛있어"]:
        cid, hits = classify(text)
        ok = cid != "anger.irritation"
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 일상어와 겹쳐 뺀 기존 키워드들. 다시 넣으면 여기서 걸린다.
    # (taxonomy.yaml normalization 위쪽 "사전 일괄 보강" 주석의 표와 같은 목록)
    print("\n일괄 보강 — 일상어 충돌로 뺀 키워드")
    print("-" * 76)
    # "여유"만 예외로 되살렸다 — calm.ease의 세분류 label이 "여유"라서, 빼면
    # label 단독 입력이 분류되지 않는다(선택 UI가 쓰는 값이다). 그 대가로
    # "여유 자금이 없어"는 평온으로 간다. label 보장이 더 중요하다고 봤다.
    for text in ["무료 배송이래", "한가운데 서 있었어",
                 "교통 정체가 심해", "정체가 뭐야", "배터리 방전됐어", "포인트 소진했어",
                 "한계효용 체감의 법칙", "균형 잡힌 식단", "고요한 밤 거룩한 밤",
                 "잔잔한 파도 소리", "영화 보고 싶어", "상실 신고를 했어"]:
        cid, hits = classify(text)
        ok = cid is None
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 세분류당 최소 개수 — 다시 빈약해지면 알아차린다
    print("\n세분류별 키워드 수 (최소 30개)")
    print("-" * 76)
    thin = []
    for c in tax["categories"]:
        for s in c["subcategories"]:
            n = len(s["keywords"])
            if n < 30:
                thin.append(f"{s['id']}({n})")
    total = sum(len(s["keywords"]) for c in tax["categories"] for s in c["subcategories"])
    print(f"{'X  ' if thin else '   '}합계 {total}개 / 24개 세분류"
          f"{' — 30개 미만: ' + ', '.join(thin) if thin else ' — 전부 30개 이상'}")
    if thin:
        failures.append("세분류 키워드 부족")

    # --- 10) 자책 / 부담감 경계선 (2026-08-16) -------------------------------
    #
    # taxonomy.yaml safety의 [경계선 원칙]을 코드로 고정한다.
    #   자책 = 결과에 대한 책임 귀속  → 위기 아님. 미분류로 두고 선택 UI로 보낸다.
    #   부담감 = 자기 존재에 대한 판단 → 위기.
    # 이 두 줄이 흔들리면 여기서 걸린다. 어느 방향으로 흔들려도 위험하다 —
    # 자책을 통째로 위기로 넣으면 상담 안내가 남발되어 진짜 위기에서 무게가 떨어지고,
    # 부담감을 "그냥 자책"이라며 빼면 자살 위험 지표를 놓친다.
    print("\n부담감 표현은 위기다 (자기 존재에 대한 판단)")
    print("-" * 76)
    for text in [
        "나만 없으면 다 잘될 텐데",
        "내가 없어야 다들 편할 거야",
        "나 같은 건 없는 게 나아",
        "내가 사라지는 게 낫겠어",
        "내가 사라져야 끝날 것 같아",
        "살 자격이 없어",
        "나는 짐만 되는 존재야",
        "내가 태어나지 말았어야 했어",
    ]:
        cid, hits = classify(text)
        ok = cid == "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<28} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    print("\n자책 자체는 위기가 아니다 (결과에 대한 책임 귀속)")
    print("-" * 76)
    for text in [
        "내가 다 망쳤어",
        "나 때문이야 미안해",
        "내 잘못이야",
        "자책하게 돼",
        "나 때문에 회의가 늦어졌어",
        "괜히 나 때문에 분위기 어색해졌어",
        "나 때문에 다 망했어",  # 결과를 탓한다 — 존재를 탓하는 게 아니다
    ]:
        cid, hits = classify(text)
        ok = cid != "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<28} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    # 어간을 좁혀 제거한 오탐. 다시 넓히면 여기서 걸린다.
    print("\n부담감 어간 오탐 방지")
    print("-" * 76)
    for text in ["살 자격증 땄어", "내가 사라지는 마술 배웠어", "짐만 늘었네", "이삿짐만 남았어"]:
        cid, hits = classify(text)
        ok = cid != "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<28} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    # 감수하기로 한 오탐. 고쳐진 게 아니라 **의도적으로 남긴 것**이라 여기 적어둔다.
    # "나만없으면"은 같은 표현이 정반대 뜻이 되는 양면적 어구라 키워드로 못 가른다.
    # 상담 안내를 불필요하게 보여주는 방향이라 감수한다.
    # 어느 날 이게 위기로 안 잡히면 "나만없으면"이 빠진 것이니 그때 확인한다.
    # --- 11) 존재를 묻는 표현 (2026-08-16) -----------------------------------
    #
    # "나는 왜 태어났을까"가 미분류였다. 경계선 원칙상 존재 자체를 묻는 것이라 위기다.
    # 어간을 그대로 쓰면 오탐 9/9였고(사람들이 왜 사는지 / 이 제품이 태어난 이유),
    # 두 앵커로 가른다 — (1) 1인칭, (2) 의문·부정.
    print("\n존재를 묻는 표현은 위기다")
    print("-" * 76)
    for text in [
        "나는 왜 태어났을까",
        "왜 태어났는지 모르겠어",
        "내가 왜 태어났나 싶어",
        "태어난 이유를 모르겠어",
        "태어난 이유가 없는 것 같아",
        "내가 태어난 이유가 뭘까",
        "존재 이유가 없어",
        "내 존재 이유가 뭔지",
        "왜 사는지 모르겠어",
        "왜 살아야 하는지 모르겠어",
        "왜 살아야 할지 모르겠어",
    ]:
        cid, hits = classify(text)
        ok = cid == "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<30} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    # 앵커 (1) 1인칭 — 사물·타인이 주어면 무해한 일상 어구다.
    print("\n존재 표현 오탐 방지 — 사물·타인 주어")
    print("-" * 76)
    for text in ["사람들이 왜 사는지 궁금해", "다들 왜 사는지 한 번쯤 생각하잖아",
                 "고양이는 왜 사는지 몰라도 행복해 보여", "이 제품이 태어난 이유가 궁금해",
                 "이 제품이 태어난 이유가 뭘까", "이 기능의 존재 이유가 뭔지",
                 "존재 이유가 분명한 제품이야", "왜 살아야 하는지에 대한 강의 들었어"]:
        cid, hits = classify(text)
        ok = cid != "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<30} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    # 앵커 (2) 의문·부정 — 이게 없으면 자기 긍정이 위기로 간다.
    # 의미를 찾은 사람에게 상담 안내를 내미는 건 사물 오탐보다 나쁘다.
    print("\n존재 표현 오탐 방지 — 긍정·해소 (앵커 2가 지키는 지점)")
    print("-" * 76)
    for text in ["내가 태어난 이유가 있다고 믿어", "왜 태어났는지 이제 알겠어",
                 "태어난 이유를 찾았어", "존재 이유가 분명해졌어",
                 "내 존재 이유가 뚜렷해졌어", "왜 사는지 알 것 같아",
                 "왜 살아야 하는지 알게 됐어"]:
        cid, hits = classify(text)
        ok = cid != "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<30} → {cid}  {hits[:1]}")
        if not ok:
            failures.append(text)

    # --- 11.5) 비하성 관용어·부정 평가 (2026-08-18) --------------------------
    #
    # "거지같아"가 미분류였다. 어간을 어디까지 줄이느냐가 또 결과를 가른 사례다.
    print("\n비하성 관용어·부정 평가")
    print("-" * 76)
    for text, expected in [
        ("거지같아", "anger.irritation"),
        ("거지같은 하루였어", "anger.irritation"),
        ("개떡같네", "anger.irritation"),
        ("엿같아 진짜", "anger.irritation"),
        ("별로네", "anger.irritation"),
        ("별로더라", "anger.irritation"),
        ("별로였어", "anger.irritation"),
        ("최악이야", "anger.irritation"),
        ("오늘 최악이다", "anger.irritation"),
    ]:
        cid, hits = classify(text)
        ok = cid == expected
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}  {hits[:2]}")
        if not ok:
            failures.append(text)

    # 어간을 줄이면 걸리는 것들. taxonomy.yaml의 ⛔ 표시와 같은 목록이다.
    print("\n비하성 관용어 어간 오탐 방지")
    print("-" * 76)
    for text in [
        "거지 소굴 같은 방",      # 거지  — 비하가 아니다
        "거지꼴로 나갔어",
        "엿 사 먹었어",           # 엿    — 먹는 엿
        "엿가락처럼 늘어졌어",
        "개떡 먹었어",
        "별로 야근이 많아",       # 별로야 — 정규화가 공백을 지운다
        "별로 야한 장면 없어",
        "별로 야식 안 먹어",
        "최악이 아니야",          # 최악이 — 부정·해소 표현
        "최악이 지나갔어",
    ]:
        cid, hits = classify(text)
        ok = cid != "anger.irritation"
        print(f"{'   ' if ok else 'X  '}{text:<24} → {cid}  {hits[:2]}")
        if not ok:
            failures.append(text)

    # --- 12) 정상 동작 — 고치려 들지 말 것 -----------------------------------
    #
    # 아래 두 가지는 **미분류인 것이 옳다.** 버그로 보고 고치면 안 된다.
    # 미분류를 발견하면 사전에 넣고 싶어지는 게 자연스러운 반응이라 여기 못박아 둔다.
    print("\n정상 동작 — 미분류가 옳다 (고치지 말 것)")
    print("-" * 76)

    # (1) 자책은 위기가 아니다. 경계선 원칙 그대로 선택 UI로 간다.
    #     위기로 옮기면 상담 안내가 남발되어 진짜 위기에서 무게가 떨어진다.
    for text in ["내가 다 망쳤어", "나 때문이야", "내 잘못이야"]:
        cid, hits = classify(text)
        ok = cid is None
        print(f"{'   ' if ok else 'X  '}{text:<30} → {cid}  (자책 — 선택 UI로 간다)")
        if not ok:
            failures.append(f"{text} — 자책이 분류됐다. 경계선 원칙 확인 필요")

    # (2) "살자격이없"으로 좁힌 덕분에 자기 긍정이 안 걸린다.
    #     ⛔ 어간을 "살자격"으로 줄이면 "난 살 자격이 있어"가 위기로 간다. 절대 줄이지 말 것.
    for text in ["난 살 자격이 있어", "나도 살 자격이 있는 사람이야"]:
        cid, hits = classify(text)
        ok = cid != "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<30} → {cid}  (자기 긍정 — 위기가 아니다)")
        if not ok:
            failures.append(f"{text} — 자기 긍정이 위기로 갔다. 살자격이없을 줄이지 말 것")

    print("\n감수한 오탐 (양면적 어구 — 위기로 잡히는 게 현재 의도다)")
    print("-" * 76)
    for text in ["나만 없으면 팀이 안 돌아가", "나만 없으면 다들 심심할걸"]:
        cid, _ = classify(text)
        ok = cid == "CRISIS"
        print(f"{'   ' if ok else 'X  '}{text:<28} → {cid}  (감수 중)")
        if not ok:
            failures.append(f"{text} — 감수 대상이 아니게 됐다. 키워드 확인 필요")

    print("\n" + "=" * 76)
    if failures:
        print(f"실패 {len(failures)}건: {', '.join(failures)}")
        print("taxonomy.yaml의 keywords에 해당 어간을 추가하세요.")
        return EXIT_FAIL
    print("전부 통과")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
