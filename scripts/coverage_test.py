#!/usr/bin/env python
"""실사용 문장 커버리지 측정 — 네트워크 호출 없음.

    python scripts/coverage_test.py
    python scripts/coverage_test.py --compare HEAD    # 커밋 대비 얼마나 좋아졌나

PLAN.md Phase 2의 "구어체 실사용 문장 100개 수동 테스트셋"을 겸한다.
normalize_test.py가 "이 표현은 이 세분류여야 한다"를 고정한다면,
여기는 **사전이 실사용 문장을 얼마나 덮는가**를 잰다. 목적이 다르다.

문장 하나에 붙는 표시
    대분류 id  — 이 대분류로 가야 한다 (세분류까지는 묻지 않는다.
                 "힘들어"가 tired인지 burnout인지는 사람도 갈리기 때문이다)
    None       — 사전으로는 못 잡는 문장형 표현. 미매칭이 정상이다.
                 Phase 2(온디바이스 모델)가 필요한지 판단하는 재료다.

sentence_form이 늘어난다고 사전을 넓히지 않는다. 은유·서술형은 어간 매칭의
사정거리 밖이고, 억지로 넓히면 오탐만 커진다 — 그래서 여기 따로 모아둔다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.normalize import normalize

ROOT = Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_FAIL = 0, 1

# 매칭률이 이 아래로 떨어지면 실패시킨다. 사전이 조용히 빈약해지는 걸 막는다.
MIN_COVERAGE = 0.80

# (문장, 기대 대분류 | None)  None = 사전으로 못 잡는 문장형
CORPUS: list[tuple[str, str | None]] = [
    # --- 불안 ---
    ("발표 앞두고 너무 떨려", "anxiety"),
    ("면접 생각하면 잠이 안 와", "anxiety"),
    ("계속 최악을 생각하게 돼", "anxiety"),
    ("자꾸 안 좋은 일이 생길 것 같아", "anxiety"),
    ("마음이 급해서 아무것도 손에 안 잡혀", "anxiety"),
    ("결과 나올 때까지 안절부절못하겠어", "anxiety"),
    # 알려진 미달 1건 — 사전으로 가르기 어렵다는 걸 기록해 두는 자리다.
    # 신체 표현("심장이 뛴다", "손에 땀")은 불안과 설렘이 그대로 공유한다.
    # 지금은 설렘으로 간다(두근+심장이 2개가 걸려 개수에서 이긴다).
    # 어느 쪽인지는 맥락이 정하는 것이라 어간을 손봐서 뒤집지 않는다 —
    # 뒤집으면 진짜 설렘 문장이 불안으로 넘어갈 뿐이다. Phase 2 판단 재료.
    ("심장이 계속 두근거리고 손에 땀이 나", "anxiety"),
    ("걱정돼서 아무것도 못 하겠어", "anxiety"),
    # --- 분노 ---
    ("아 진짜 짜증나 죽겠네", "anger"),
    ("씨발 왜 나한테만 이래", "anger"),
    ("시발 진짜 열받네", "anger"),
    ("개같은 하루였어", "anger"),
    ("존나 짜증나는 일이 있었어", "anger"),
    ("억울해서 잠이 안 와", "anger"),
    ("왜 나만 이런 대우를 받아야 해", "anger"),
    ("싸우고 싶어 미치겠어", "anger"),
    ("참을 수가 없어 폭발할 것 같아", "anger"),
    ("어이가 없어서 말도 안 나와", "anger"),
    # --- 답답함 ---
    ("뭘 해야 할지 하나도 모르겠어", "frustration"),
    ("아무리 해도 진전이 없어", "frustration"),
    ("이해되지 않아 답답해", "frustration"),
    ("이해가 안 돼서 미치겠어", "frustration"),
    ("말하고 싶은데 계속 삼키게 돼", "frustration"),
    ("눈치 보느라 아무 말도 못 했어", "frustration"),
    ("제자리걸음만 반복하는 기분이야", "frustration"),
    ("터질 것 같아", "frustration"),
    ("앞이 캄캄해", "frustration"),
    # --- 우울 ---
    ("오늘따라 기분이 처진다", "sadness"),
    ("기분이 눅눅해", "sadness"),
    ("이유 없이 눈물이 나", "sadness"),
    ("가슴이 먹먹해", "sadness"),
    ("헛헛하고 쓸쓸해", "sadness"),
    ("연락할 사람이 아무도 없어", "sadness"),
    ("혼자인 것 같은 밤이야", "sadness"),
    ("그 사람 빈자리가 너무 커", "sadness"),
    ("아직도 미련이 남아", "sadness"),
    ("너무 보고 싶어서 힘들어", "sadness"),
    ("울고 싶은데 눈물이 안 나", "sadness"),
    # --- 지침 ---
    ("너무 힘들다", "exhaustion"),
    ("오늘 진짜 힘드네", "exhaustion"),
    ("도망치고 싶어", "exhaustion"),
    ("다 그만두고 싶어", "exhaustion"),
    ("완전히 방전된 느낌이야", "exhaustion"),
    ("아무것도 하기 싫어", "exhaustion"),
    ("의욕이 하나도 없어", "exhaustion"),
    ("몸이 무겁고 계속 졸려", "exhaustion"),
    ("번아웃이 온 것 같아", "exhaustion"),
    ("귀찮아서 손도 안 가", "exhaustion"),
    # --- 기쁨 ---
    ("드디어 해냈어 너무 뿌듯해", "joy"),
    ("합격했어 진짜 자랑스러워", "joy"),
    ("오늘 하루가 너무 즐거웠어", "joy"),
    ("기분 완전 상쾌해", "joy"),
    ("고마운 사람이 많은 하루였어", "joy"),
    ("감사한 마음이 벅차올라", "joy"),
    ("보람 있는 하루였어", "joy"),
    # --- 설렘 ---
    ("내일이 너무 기대돼", "flutter"),
    ("여행 갈 생각에 설레", "flutter"),
    ("심장이 두근두근해", "flutter"),
    ("자꾸 생각나서 잠이 안 와", "flutter"),
    ("들뜬 마음을 주체할 수가 없어", "flutter"),
    # --- 평온 ---
    ("오랜만에 마음이 편안해", "calm"),
    ("느긋하게 커피 한잔했어", "calm"),
    ("마음이 차분해졌어", "calm"),
    ("걱정이 없어져서 홀가분해", "calm"),
    ("주말이라 여유가 있어", "calm"),
    # --- 심심함 ---
    ("너무 심심해 뭐하지", "boredom"),
    ("하루가 지루하고 따분해", "boredom"),
    ("매일 똑같아서 재미없어", "boredom"),
    ("뭔가 새로운 걸 해보고 싶어", "boredom"),
    ("기분 전환이 필요해", "boredom"),
    # --- 문장형: 사전으로는 못 잡는다 (Phase 2 판단 재료) ---
    ("입가에 미소가 절로 지어지네요", None),
    ("하늘이 유난히 파랗게 보이는 하루", None),
    ("가슴 한켠이 저릿하게 내려앉았다", None),
    ("발걸음이 자꾸 무거워지는 저녁이에요", None),
    # 문장형으로 넣었다가 옮겼다 — "눈시울"이 잡아낸다. 어간이 넓어져 우연히
    # 걸린 게 아니라 감정 어휘가 문장 안에 그대로 들어 있던 경우다.
    ("창밖을 보는데 문득 눈시울이 뜨거워졌어요", "sadness"),
    ("세상이 나만 빼고 돌아가는 것 같은 날", None),
    ("어깨에 누가 올라탄 것처럼 무거워요", None),
    ("숨을 크게 쉬어도 채워지지 않는 기분", None),
    ("오늘은 이상하게 발이 가볍네요", None),
    ("시간이 물처럼 흘러가 버렸어요", None),
]


def load_taxonomy_from(ref: str | None) -> dict:
    if ref is None:
        return yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    blob = subprocess.run(
        ["git", "show", f"{ref}:taxonomy.yaml"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return yaml.safe_load(blob)


def classify(tax: dict, text: str) -> tuple[str | None, str | None]:
    """(대분류, 세분류) — 못 잡으면 (None, None)."""
    n = normalize(text)
    if not n:
        return None, None
    for kw in tax["safety"]["crisis_keywords"]:
        if normalize(kw) in n:
            return "safety", "CRISIS"
    best = None
    for c in tax["categories"]:
        for s in c["subcategories"]:
            hits = [k for k in s["keywords"] if normalize(k) in n]
            if hits:
                score = (len(hits), sum(len(normalize(k)) for k in hits))
                if best is None or score > best[0]:
                    best = (score, c["id"], s["id"])
    if best:
        return best[1], best[2]
    for c in tax["categories"]:
        if [k for k in (c.get("keywords") or []) if normalize(k) in n]:
            return c["id"], None  # 대분류까지만 — 선택 UI로 넘어간다
    return None, None


def measure(tax: dict) -> dict:
    hit = wrong = 0
    misses: list[str] = []
    sentence_caught: list[tuple[str, str]] = []
    expected = [(t, e) for t, e in CORPUS if e is not None]
    for text, want in CORPUS:
        parent, _ = classify(tax, text)
        if want is None:
            # 문장형은 미매칭이 정상. 잡혔다면 그것대로 기록해 둔다.
            if parent is not None:
                sentence_caught.append((text, parent))
            continue
        if parent is None:
            misses.append(text)
        elif parent != want:
            wrong += 1
            misses.append(f"{text}  (→ {parent}, 기대 {want})")
        else:
            hit += 1
    return {
        "total": len(expected),
        "hit": hit,
        "wrong": wrong,
        "misses": misses,
        "sentence_caught": sentence_caught,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", metavar="REF", help="이 커밋의 taxonomy.yaml과 비교")
    args = ap.parse_args()

    now = measure(load_taxonomy_from(None))
    cov = now["hit"] / now["total"]

    print(f"실사용 문장 {len(CORPUS)}개 "
          f"(기대 대분류 있음 {now['total']}개 / 문장형 {len(CORPUS) - now['total']}개)")
    print("=" * 76)

    if args.compare:
        before = measure(load_taxonomy_from(args.compare))
        bcov = before["hit"] / before["total"]
        print(f"{args.compare:<12} 매칭 {before['hit']:>3}/{before['total']}  "
              f"({bcov * 100:5.1f}%)  오분류 {before['wrong']}건")
        print(f"{'현재':<12} 매칭 {now['hit']:>3}/{now['total']}  "
              f"({cov * 100:5.1f}%)  오분류 {now['wrong']}건")
        print(f"{'':12} 실패율 {(1 - bcov) * 100:.1f}% → {(1 - cov) * 100:.1f}%"
              f"  ({(bcov - cov) * 100:+.1f}%p)")
        print()

    if now["misses"]:
        print(f"미매칭·오분류 {len(now['misses'])}건")
        for m in now["misses"]:
            print(f"   {m}")
        print()

    print(f"문장형 {len(CORPUS) - now['total']}개 — 사전 사정거리 밖 (Phase 2 판단 재료)")
    if now["sentence_caught"]:
        # 잡혔다고 좋은 게 아니다. 어간이 넓어져 우연히 걸린 것일 수 있다.
        print("   ※ 아래는 잡혔다. 의도한 것인지 어간이 넓어진 탓인지 확인할 것:")
        for text, parent in now["sentence_caught"]:
            print(f"      {text}  → {parent}")
    else:
        print("   전부 미매칭 — 예상대로다. 사전을 넓혀 잡으려 하지 말 것.")

    print("\n" + "=" * 76)
    print(f"커버리지 {cov * 100:.1f}%  (하한 {MIN_COVERAGE * 100:.0f}%)")
    if cov < MIN_COVERAGE:
        print("사전이 하한 아래로 떨어졌다 — taxonomy.yaml의 keywords를 확인하세요.")
        return EXIT_FAIL
    print("통과")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
