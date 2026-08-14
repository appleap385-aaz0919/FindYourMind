/**
 * Python 구현을 정답으로 삼아 정규화 패리티 픽스처를 만든다.
 *
 *   node test/gen-normalize-fixture.mjs
 *
 * taxonomy.yaml의 위기 키워드·감정 키워드를 실제 매칭 대상으로 넣고,
 * 두 구현이 갈릴 만한 경계 입력(한자·가나·악센트·이모지·자모·반복)을 함께 던진다.
 */

import { execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");

const taxonomy = JSON.parse(
  readFileSync(join(here, "..", "src", "data", "taxonomy.json"), "utf8"),
);

const INPUTS = [
  // --- normalize_test.py에 있는 실사용 문장 ---
  "마음이 급해 죽겠어", "마음이급해죽겠어", "마 음 이  급 해",
  "짜증나아아아아!!!", "너무 외로워ㅠㅠㅠㅠ", "아무것도 하기 싫다...",
  "아무것도하기싫다", "발표 앞두고 너무 떨림", "요즘 계속 제자리인 것 같아",
  "그냥 다 놓고 싶어", "합격했어!!! 너무 뿌듯", "심심해 뭐하지",
  // --- 자모·반복·문장부호 경계 ---
  "죽 고 싶", "죽고싶ㅠㅠㅠ", "죽!고!싶!", "ㅜㅜㅜㅜ", "ㅋㅋㅋㅋㅋ", "ㅎㅏ...",
  // --- JS \w 와 Python \w 가 갈리는 지점 ---
  "스트레스 STRESS Stress", "카페에서 커피 ☕ 한 잔",
  "漢字가 섞인 입력", "ひらがな 混ざり", "café naïve résumé",
  "emoji 🎧🌊 섞임", "밑줄_포함", "숫자123 混在",
  "Ⅻ 로마숫자", "①②③ 원문자", "ＦＵＬＬＷＩＤＴＨ",
  // --- 공백·빈 문자열 ---
  "   ", "\t\n", "a", "",
];

const CRISIS = taxonomy.safety.crisis_keywords;
const SOME_KEYWORDS = taxonomy.categories[0].subcategories[0].keywords.slice(0, 12);

const MATCH_CASES = [
  ...INPUTS.map((haystack) => ({ haystack, terms: CRISIS })),
  ...INPUTS.map((haystack) => ({ haystack, terms: SOME_KEYWORDS })),
];

const py = `
import json, sys
sys.path.insert(0, r"${join(repo, "scripts").replace(/\\/g, "\\\\")}")
from lib.normalize import normalize, matched_terms
payload = json.loads(sys.stdin.read())
out = {
    "normalize": [{"input": s, "expected": normalize(s)} for s in payload["inputs"]],
    "matched": [
        {"haystack": c["haystack"], "terms": c["terms"],
         "expected": matched_terms(c["haystack"], c["terms"])}
        for c in payload["match_cases"]
    ],
}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
`;

const result = execFileSync("python", ["-X", "utf8", "-c", py], {
  input: JSON.stringify({ inputs: INPUTS, match_cases: MATCH_CASES }),
  encoding: "utf8",
  maxBuffer: 32 * 1024 * 1024,
});

mkdirSync(join(here, "fixtures"), { recursive: true });
writeFileSync(
  join(here, "fixtures", "normalize-cases.json"),
  JSON.stringify(JSON.parse(result), null, 2),
  "utf8",
);

const parsed = JSON.parse(result);
console.log(
  `픽스처 생성 — normalize ${parsed.normalize.length}건 / matched ${parsed.matched.length}건 (정답: Python 구현)`,
);
