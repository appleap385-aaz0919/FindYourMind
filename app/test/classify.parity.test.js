/**
 * classify.js ↔ scripts/lib/classify.py 동등성 검사.
 *
 * 왜 있나 (2026-08-18)
 *   분류 알고리즘이 두 곳에 있다. 사전을 고칠 때 검증은 Python으로 하는데
 *   (normalize_test·coverage_test) 사용자가 보는 것은 JS다.
 *   두 구현이 갈리면 Python 테스트는 통과하면서 화면만 틀린다 —
 *   "테스트가 실제 소스를 읽는지 확인한다"의 분류판이다.
 *
 * 기대값은 사람이 손으로 적지 않는다. Python 구현에 같은 입력을 넣어
 * 그 출력을 정답으로 삼는다 (fixtures/classify-cases.json).
 *
 * 픽스처 재생성:  node test/gen-classify-fixture.mjs
 *   → taxonomy.yaml을 고쳤으면 npm run gen:taxonomy 다음에 이걸 돌린다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { classify, RESULT } from "../src/lib/classify.js";

const here = dirname(fileURLToPath(import.meta.url));
const taxonomy = JSON.parse(
  readFileSync(join(here, "..", "src", "data", "taxonomy.json"), "utf8"),
);
const fixture = JSON.parse(
  readFileSync(join(here, "fixtures", "classify-cases.json"), "utf8"),
);

/** Outcome(JS) → 픽스처와 같은 모양으로 */
function shape(outcome) {
  return {
    kind: outcome.kind,
    category: outcome.category?.id ?? null,
    subcategory: outcome.subcategory?.id ?? null,
  };
}

test("classify()가 Python 구현과 같은 판정을 낸다", () => {
  const mismatches = [];
  for (const expected of fixture.cases) {
    const actual = shape(classify(expected.input, taxonomy));
    if (
      actual.kind !== expected.kind ||
      actual.category !== expected.category ||
      actual.subcategory !== expected.subcategory
    ) {
      mismatches.push({ input: expected.input, expected, actual });
    }
  }
  assert.deepEqual(
    mismatches,
    [],
    `${mismatches.length}건 불일치:\n` +
      mismatches
        .map(
          (m) =>
            `  ${JSON.stringify(m.input)}\n` +
            `    py=${m.expected.kind}/${m.expected.category}/${m.expected.subcategory}\n` +
            `    js=${m.actual.kind}/${m.actual.category}/${m.actual.subcategory}`,
        )
        .join("\n"),
  );
});

test("픽스처가 taxonomy와 함께 갱신됐다", () => {
  // 사전을 고치고 픽스처를 안 만들면 패리티 검사가 낡은 사전을 보게 된다.
  //
  // ⚠ label만 보면 **키워드 추가를 놓친다.** 세분류 이름은 그대로인 채
  //   keywords만 늘어나는 것이 가장 흔한 변경이다(2026-08-18 어휘 보충).
  //   그래서 개수까지 함께 잰다.
  const REGEN = "node test/gen-classify-fixture.mjs를 돌리세요";

  const labels = new Set();
  for (const category of taxonomy.categories) {
    labels.add(category.label);
    for (const sub of category.subcategories) labels.add(sub.label);
  }
  const covered = new Set(fixture.cases.map((c) => c.input));
  const missing = [...labels].filter((l) => !covered.has(l));
  assert.deepEqual(missing, [], `픽스처에 없는 label ${missing.length}개 — ${REGEN}`);

  assert.ok(fixture.taxonomy, `픽스처에 taxonomy 요약이 없다 (옛 형식) — ${REGEN}`);

  const now = {
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
  assert.deepEqual(
    now,
    fixture.taxonomy,
    `사전이 픽스처 생성 이후에 바뀌었다 — ${REGEN}\n` +
      `  지금:   ${JSON.stringify(now)}\n` +
      `  픽스처: ${JSON.stringify(fixture.taxonomy)}`,
  );
});

test("위기 판정은 두 구현 모두에서 감정보다 먼저다", () => {
  // 픽스처가 비어도(생성 실패) 이 불변식만은 직접 확인한다.
  assert.equal(classify("답답해서 죽고싶다", taxonomy).kind, RESULT.CRISIS);
  const crisisCase = fixture.cases.find((c) => c.input === "답답해서 죽고싶다");
  assert.ok(crisisCase, "픽스처에 위기 케이스가 없다");
  assert.equal(crisisCase.kind, "crisis");
});
