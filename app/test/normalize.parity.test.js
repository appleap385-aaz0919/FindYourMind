/**
 * normalize.js ↔ scripts/lib/normalize.py 동등성 검사.
 *
 * 케이스와 기대값은 사람이 손으로 적지 않는다. Python 구현에 같은 입력을 넣어
 * 그 출력을 정답으로 삼는다 (fixtures/normalize-cases.json).
 * 손으로 적으면 두 구현이 함께 틀렸을 때 테스트도 같이 틀린다.
 *
 * 픽스처 재생성:  node test/gen-normalize-fixture.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { normalize, matchedTerms, containsAny } from "../src/lib/normalize.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, "fixtures", "normalize-cases.json"), "utf8"),
);

test("normalize()가 Python 구현과 문자 단위로 일치한다", () => {
  const mismatches = [];
  for (const { input, expected } of fixture.normalize) {
    const actual = normalize(input);
    if (actual !== expected) mismatches.push({ input, expected, actual });
  }
  assert.deepEqual(
    mismatches,
    [],
    `${mismatches.length}건 불일치:\n` +
      mismatches
        .map((m) => `  ${JSON.stringify(m.input)}\n    py=${JSON.stringify(m.expected)}\n    js=${JSON.stringify(m.actual)}`)
        .join("\n"),
  );
});

test("matchedTerms()가 Python 구현과 일치한다", () => {
  for (const { haystack, terms, expected } of fixture.matched) {
    assert.deepEqual(
      matchedTerms(haystack, terms),
      expected,
      `haystack=${JSON.stringify(haystack)}`,
    );
  }
});

test("containsAny()는 matchedTerms()의 비어있지 않음과 같다", () => {
  for (const { haystack, terms, expected } of fixture.matched) {
    assert.equal(containsAny(haystack, terms), expected.length > 0);
  }
});

test("빈 입력·null을 안전하게 처리한다", () => {
  assert.equal(normalize(""), "");
  assert.equal(normalize(null), "");
  assert.equal(normalize(undefined), "");
  assert.deepEqual(matchedTerms("", ["죽고싶"]), []);
  assert.equal(containsAny("", ["죽고싶"]), false);
});
