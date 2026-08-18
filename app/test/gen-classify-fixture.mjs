/**
 * Python 구현을 정답으로 삼아 분류 패리티 픽스처를 만든다.
 *
 *   node test/gen-classify-fixture.mjs
 *
 * 왜 필요한가
 *   분류 알고리즘은 scripts/lib/classify.py와 src/lib/classify.js 두 곳에 있다.
 *   사전을 고칠 때 검증은 Python으로 하는데(normalize_test·coverage_test)
 *   사용자가 보는 것은 JS다. 두 구현이 갈리면 Python 테스트는 통과하면서
 *   화면만 틀린다 — normalize가 이미 같은 이유로 묶여 있다.
 *
 * 기대값은 사람이 손으로 적지 않는다. 손으로 적으면 두 구현이 함께 틀렸을 때
 * 테스트도 같이 틀린다.
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

// 입력은 실제 사전에서 뽑는다 — 손으로 고른 몇 개보다 갈림 지점을 잘 덮는다.
const INPUTS = [
  // 위기 경로가 감정보다 먼저인지
  "죽고싶다", "답답해서 죽고싶다", "짜증나 짜증나 진짜 죽고싶어",
  // 자기 지향 / 타인 지향이 갈리는 지점
  "죽여버리고 싶어", "나를 죽이고 싶어", "나만 없으면 다 잘될 텐데",
  // 점수 규칙(매칭 수 → 길이 합)이 실제로 갈리는 입력
  "웃음이 터질 것 같아", "눈물이 터질 것 같아", "속이 터질 것 같아",
  "가슴이 답답하고 불안해", "대박 터질 것 같아", "빵 터질 것 같아",
  // 대분류 폴백 / 무매칭
  "답답해", "혼란스러워", "qqqqzzzz", "", "   ",
  // 2026-08-18 보충 어휘와 배제 어간
  "못마땅해", "너무 속상해", "울음이 북받쳐 올라", "진짜 맥빠진다",
  "전세 계약 올라서 부담이야", "애처로운 눈빛으로 쳐다보더라",
  "눈물겨운 노력 끝에 성공했대", "앞날이 암담해",
  // 정규화가 걸리는 형태
  "마 음 이  급 해", "짜증나아아아아!!!", "너무 외로워ㅠㅠㅠㅠ",
];

// 전 세분류·대분류 label을 통째로 넣는다 (label 회귀가 두 구현에서 같아야 한다)
for (const category of taxonomy.categories) {
  INPUTS.push(category.label);
  for (const sub of category.subcategories) INPUTS.push(sub.label);
}

const py = `
import json, sys
sys.path.insert(0, r"${join(repo, "scripts").replace(/\\/g, "\\\\")}")
from lib.classify import classify
payload = json.loads(sys.stdin.read())
tax = payload["taxonomy"]
out = []
for text in payload["inputs"]:
    o = classify(text, tax)
    out.append({
        "input": text,
        "kind": o.kind,
        "category": o.category_id,
        "subcategory": o.subcategory_id,
    })
sys.stdout.write(json.dumps({"cases": out, "taxonomy": payload["summary"]}, ensure_ascii=False))
`;

/**
 * 픽스처가 어느 사전으로 만들어졌는지 남긴다.
 *
 * label만으로는 **키워드 추가를 놓친다** — 세분류 이름은 그대로인 채
 * keywords만 늘어나는 것이 가장 흔한 변경이다(2026-08-18 어휘 보충이 그랬다).
 * 그러면 패리티가 낡은 사전을 보면서 계속 초록불이 된다.
 */
const summary = {
  keywords: taxonomy.categories.reduce(
    (sum, c) => sum + c.subcategories.reduce((s, x) => s + x.keywords.length, 0),
    0,
  ),
  categoryKeywords: taxonomy.categories.reduce(
    (sum, c) => sum + (c.keywords?.length ?? 0),
    0,
  ),
  crisisKeywords: taxonomy.safety.crisis_keywords.length,
  subcategories: taxonomy.categories.reduce(
    (sum, c) => sum + c.subcategories.length,
    0,
  ),
};

const result = execFileSync("python", ["-X", "utf8", "-c", py], {
  input: JSON.stringify({ inputs: INPUTS, taxonomy, summary }),
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
});

mkdirSync(join(here, "fixtures"), { recursive: true });
writeFileSync(
  join(here, "fixtures", "classify-cases.json"),
  JSON.stringify(JSON.parse(result), null, 2),
  "utf8",
);

console.log(
  `픽스처 생성 — classify ${JSON.parse(result).cases.length}건 ` +
    `(감정 키워드 ${summary.keywords} / 위기 ${summary.crisisKeywords}, 정답: Python 구현)`,
);
