# -*- coding: utf-8 -*-
"""정규화 매칭 검증 스크립트 (Phase 0 산출물)
띄어쓰기·반복문자·문장부호가 달라도 같은 세분류로 매칭되는지 확인한다.
앱(JS)과 배치(Python) 양쪽이 동일 로직을 구현해야 한다.
"""
import re, yaml

def normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r'[^\w가-힣ㄱ-ㅎㅏ-ㅣa-z0-9]', '', t)   # 공백·문장부호·이모지 제거
    t = re.sub(r'(.)\1{2,}', r'\1\1', t)              # 3회 이상 반복 → 2회
    t = t.replace('ㅜ', 'ㅠ')
    return t

tax = yaml.safe_load(open('taxonomy.yaml'))

def classify(text):
    n = normalize(text)
    for kw in tax['safety']['crisis_keywords']:
        if normalize(kw) in n:
            return ('CRISIS', kw)
    best = None
    for c in tax['categories']:
        for s in c['subcategories']:
            hits = [k for k in s['keywords'] if normalize(k) in n]
            if hits:
                score = (len(hits), sum(len(normalize(k)) for k in hits))
                if best is None or score > best[0]:
                    best = (score, s['id'], s['label'], hits)
    return (best[1], best[3]) if best else (None, [])

cases = [
    "마음이 급해 죽겠어",      # 띄어쓰기 있음
    "마음이급해죽겠어",         # 띄어쓰기 없음
    "마 음 이  급 해",          # 띄어쓰기 과다
    "짜증나아아아아!!!",        # 반복 + 문장부호
    "너무 외로워ㅠㅠㅠㅠ",
    "아무것도 하기 싫다...",
    "아무것도하기싫다",
    "발표 앞두고 너무 떨림",
    "요즘 계속 제자리인 것 같아",
    "그냥 다 놓고 싶어",
    "합격했어!!! 너무 뿌듯",
    "심심해 뭐하지",
]
print(f"{'입력':<28} → 결과")
print("-" * 70)
for c in cases:
    cid, hits = classify(c)
    print(f"{c:<28} → {cid}  {hits[:3]}")
