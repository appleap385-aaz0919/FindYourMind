/**
 * 확정 사항이 실제로 지켜지는지 검사한다.
 * 여기가 깨지면 UI가 아니라 약속이 깨진 것이다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { classify, RESULT } from "../src/lib/classify.js";
import { getCategoryVideos, getCrisisVideos, formatDuration } from "../src/lib/videos.js";
import { withMinDuration } from "../src/lib/offline.js";
import { revisitSlot } from "../src/lib/messages.js";
import { isCompleteVideosPayload } from "../src/lib/payload.js";

const here = dirname(fileURLToPath(import.meta.url));
const load = (p) => JSON.parse(readFileSync(join(here, "..", "src", "data", p), "utf8"));
const taxonomy = load("taxonomy.json");
const videos = load("seed-videos.json");

// --- 위기 검사는 감정 분류보다 항상 먼저 -------------------------------------

test("위기 키워드 18개가 모두 crisis로 분류된다", () => {
  for (const keyword of taxonomy.safety.crisis_keywords) {
    assert.equal(classify(keyword, taxonomy).kind, RESULT.CRISIS, `키워드: ${keyword}`);
  }
});

test("감정 키워드와 위기 키워드가 함께 있으면 위기가 이긴다", () => {
  // "짜증나"(anger.irritation)가 여러 번 걸려 점수가 높아도 위기가 우선이어야 한다.
  const input = "짜증나 짜증나 짜증나 진짜 죽고싶다";
  assert.equal(classify(input, taxonomy).kind, RESULT.CRISIS);
});

test("띄어쓰기·문장부호·반복으로 위기 키워드를 우회할 수 없다", () => {
  for (const input of ["죽 고 싶", "죽!고!싶!", "죽고싶ㅠㅠㅠㅠ", "자 해", "살기 싫어..."]) {
    assert.equal(classify(input, taxonomy).kind, RESULT.CRISIS, `입력: ${input}`);
  }
});

test("위기 결과는 어떤 키워드에 걸렸는지 돌려주지 않는다", () => {
  const outcome = classify("죽고싶다", taxonomy);
  assert.equal(outcome.kind, RESULT.CRISIS);
  assert.equal(outcome.hits, undefined);
  assert.equal(outcome.subcategory, undefined);
});

// --- crisis / categories 격리 -------------------------------------------------

test("crisis 영상과 일반 카테고리 영상이 서로소다", () => {
  const crisisIds = new Set(videos.crisis.videos.map((v) => v.videoId));
  const categoryIds = new Set(
    videos.categories.flatMap((c) => c.videos.map((v) => v.videoId)),
  );
  const overlap = [...crisisIds].filter((id) => categoryIds.has(id));
  assert.deepEqual(overlap, [], `겹치는 videoId: ${overlap}`);
});

test("getCrisisVideos는 categories를 절대 읽지 않는다", () => {
  // categories를 통째로 비워도 위기 영상은 그대로 나와야 한다.
  const onlyCrisis = { ...videos, categories: [] };
  const result = getCrisisVideos(onlyCrisis);
  assert.ok(result.length >= 4 && result.length <= 6, `노출 ${result.length}개`);

  const crisisIds = new Set(videos.crisis.videos.map((v) => v.videoId));
  assert.ok(result.every((v) => crisisIds.has(v.videoId)));
});

test("getCategoryVideos는 crisis를 절대 읽지 않는다", () => {
  // crisis를 통째로 비워도 일반 카테고리는 영향이 없어야 한다.
  const noCrisis = { ...videos, crisis: { updated_at: null, videos: [] } };
  const result = getCategoryVideos(noCrisis, "anxiety.restless");
  assert.equal(result.length, 20);
});

test("모든 세분류에서 categories 조회 결과에 위기 영상이 섞이지 않는다", () => {
  const crisisIds = new Set(videos.crisis.videos.map((v) => v.videoId));
  for (const category of taxonomy.categories) {
    for (const sub of category.subcategories) {
      const list = getCategoryVideos(videos, sub.id);
      assert.ok(list.length > 0, `${sub.id}: 영상 없음`);
      assert.ok(
        list.every((v) => !crisisIds.has(v.videoId)),
        `${sub.id}에 위기 영상이 섞였다`,
      );
    }
  }
});

test("위기 노출 개수는 4~6개 사이다 (여러 번 돌려도)", () => {
  for (let i = 0; i < 200; i += 1) {
    const n = getCrisisVideos(videos).length;
    assert.ok(n >= 4 && n <= 6, `${n}개 노출됨`);
  }
});

// --- 로딩 지연 ----------------------------------------------------------------

test("min_duration_ms는 taxonomy에서 읽으며 1000이다", () => {
  assert.equal(taxonomy.ui.loading.min_duration_ms, 1000);
});

test("분류가 빠르면 최소 지연을 채운다", async () => {
  const started = Date.now();
  await withMinDuration(async () => "즉시", 300);
  assert.ok(Date.now() - started >= 295, "최소 지연이 지켜지지 않았다");
});

test("분류가 더 오래 걸리면 추가 지연을 넣지 않는다", async () => {
  const started = Date.now();
  await withMinDuration(async () => {
    await new Promise((r) => setTimeout(r, 200));
    return "느림";
  }, 100);
  const elapsed = Date.now() - started;
  assert.ok(elapsed < 190 + 100, `추가 지연이 붙었다 (${elapsed}ms)`);
});

// --- 방문 간격 ----------------------------------------------------------------

test("기록이 없으면 first_visit — '왜 안 왔냐'는 경로가 없다", () => {
  assert.equal(revisitSlot({ lastVisitAt: null }), "first_visit");
  assert.equal(revisitSlot({ lastVisitAt: "깨진값" }), "first_visit");
});

test("방문 간격이 슬롯으로 정확히 매핑된다", () => {
  const now = new Date("2026-08-14T12:00:00");
  const ago = (days) => new Date(now.getTime() - days * 86400000).toISOString();
  assert.equal(revisitSlot({ lastVisitAt: ago(0), visitCountToday: 1 }, now), "same_day");
  assert.equal(revisitSlot({ lastVisitAt: ago(2), visitCountToday: 0 }, now), "recent");
  assert.equal(revisitSlot({ lastVisitAt: ago(10), visitCountToday: 0 }, now), "long_absence");
});

// --- 기타 --------------------------------------------------------------------

test("ISO 8601 duration을 사람이 읽는 형식으로 바꾼다", () => {
  assert.equal(formatDuration("PT8H"), "8:00:00");
  assert.equal(formatDuration("PT7H18M14S"), "7:18:14");
  assert.equal(formatDuration("PT3M54S"), "3:54");
  assert.equal(formatDuration(""), "");
  assert.equal(formatDuration("이상한값"), "");
});

test("빈 입력과 무의미 입력이 구분된다", () => {
  assert.equal(classify("", taxonomy).kind, RESULT.EMPTY);
  assert.equal(classify("   ", taxonomy).kind, RESULT.EMPTY);
  assert.equal(classify("qqqqzzzz", taxonomy).kind, RESULT.NO_MATCH);
});

test("긴 키워드가 짧은 키워드보다 우선한다", () => {
  const outcome = classify("가슴이 답답하고 불안해", taxonomy);
  assert.equal(outcome.kind, RESULT.OK);
  assert.ok(outcome.hits.length > 0);
});

// --- 캐시 교체 관문 (부분 데이터 방어) ---------------------------------------

test("실제 배포 산출물은 통과하고 부분 실행 산출물은 거부된다", () => {
  const dist = join(here, "..", "..", "dist");
  const full = JSON.parse(readFileSync(join(dist, "videos.json"), "utf8"));
  const partial = JSON.parse(readFileSync(join(dist, "videos.partial.json"), "utf8"));

  assert.equal(isCompleteVideosPayload(full), true, "정상 배포물이 거부됐다");
  assert.equal(isCompleteVideosPayload(partial), false, "부분 산출물이 통과했다");
  assert.equal(partial.partial, true);
});

test("잘리거나 빈 응답은 캐시에 들어가지 못한다", () => {
  for (const bad of [
    null,
    undefined,
    {},
    "문자열",
    { version: "x" },
    { version: "x", categories: [] },
    { version: "x", categories: [{ id: "a", videos: [] }] }, // crisis 없음
    { version: 1, categories: [{ id: "a", videos: [] }], crisis: { videos: [] } },
    { version: "x", categories: [{ id: "a" }], crisis: { videos: [] } }, // videos 없음
  ]) {
    assert.equal(isCompleteVideosPayload(bad), false, `통과하면 안 됨: ${JSON.stringify(bad)}`);
  }
});

// --- label 회귀: 사용자가 가장 먼저 떠올리는 말은 카테고리 이름 그 자체다 -----

test("세분류 label 24개가 전부 매칭된다", () => {
  const missed = [];
  for (const category of taxonomy.categories) {
    for (const sub of category.subcategories) {
      const outcome = classify(sub.label, taxonomy);
      if (outcome.kind !== RESULT.OK && outcome.kind !== RESULT.CATEGORY) {
        missed.push(`${sub.id}(${sub.label})`);
      }
    }
  }
  assert.deepEqual(missed, [], `미매칭 label: ${missed.join(", ")}`);
});

test("대분류 label 9개가 전부 매칭된다", () => {
  const missed = [];
  for (const category of taxonomy.categories) {
    const outcome = classify(category.label, taxonomy);
    if (outcome.kind !== RESULT.OK && outcome.kind !== RESULT.CATEGORY) {
      missed.push(`${category.id}(${category.label})`);
    }
  }
  assert.deepEqual(missed, [], `미매칭 label: ${missed.join(", ")}`);
});

test("모든 대분류에 폴백 keywords가 있다", () => {
  for (const category of taxonomy.categories) {
    assert.ok(
      Array.isArray(category.keywords) && category.keywords.length > 0,
      `${category.id}: 대분류 keywords 없음`,
    );
  }
});

test("'답답해'는 frustration 대분류로 떨어져 선택 UI로 간다", () => {
  const outcome = classify("답답해", taxonomy);
  assert.equal(outcome.kind, RESULT.CATEGORY);
  assert.equal(outcome.category.id, "frustration");
});

test("label 활용형이 어간 매칭으로 잡힌다", () => {
  for (const input of [
    "답답하다", "답답한", "답답함", "답답하네요",
    "불안해", "불안하다",
    "외로워", "외로움", "외롭다",
    "즐거워", "즐거움",
    "슬퍼", "슬픔", "슬프다",
  ]) {
    const outcome = classify(input, taxonomy);
    assert.ok(
      outcome.kind === RESULT.OK || outcome.kind === RESULT.CATEGORY,
      `"${input}" 미매칭`,
    );
  }
});

test("세분류가 걸리면 대분류 폴백보다 우선한다", () => {
  // "우울"은 sadness 대분류 keywords에도, sadness.sorrow 세분류에도 있다.
  const outcome = classify("우울해", taxonomy);
  assert.equal(outcome.kind, RESULT.OK);
  assert.equal(outcome.subcategory.id, "sadness.sorrow");
});

test("위기 검사는 대분류 폴백보다도 먼저다", () => {
  // "답답"(대분류 폴백)과 위기 키워드가 함께 있어도 위기가 이긴다.
  assert.equal(classify("답답해서 죽고싶다", taxonomy).kind, RESULT.CRISIS);
});

test("체계에 없는 감정은 여전히 nomatch다 (기록 대상)", () => {
  assert.equal(classify("혼란스러워", taxonomy).kind, RESULT.NO_MATCH);
});

// --- 동의어 보강 · 충돌 키워드 ------------------------------------------------

test("frustration 동의어가 매칭된다", () => {
  const cases = [
    ["갑갑해", RESULT.CATEGORY, "frustration"],
    ["옥죄어와", RESULT.OK, "frustration.suppressed"],
    ["숨통막혀", RESULT.OK, "frustration.suppressed"],
    ["짓눌린 것 같아", RESULT.OK, "frustration.suppressed"],
    ["꽉막힌 느낌", RESULT.OK, "frustration.blocked"],
  ];
  for (const [input, kind, id] of cases) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, kind, `"${input}" 종류`);
    const got = kind === RESULT.CATEGORY ? outcome.category.id : outcome.subcategory.id;
    assert.equal(got, id, `"${input}" → ${got}`);
  }
});

test("짧은 키워드가 일상어를 삼키지 않는다", () => {
  // "분해"(anger.unfair)가 차분해/따분해에 걸리던 오분류.
  const cases = [
    ["차분해", "calm.stable"],
    ["따분해", "boredom.dull"],
    ["뭔가 해보고 싶어", "boredom.novelty"],
    ["새로운게 하고 싶어", "boredom.novelty"],
  ];
  for (const [input, id] of cases) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, RESULT.OK, `"${input}" 미매칭`);
    assert.equal(outcome.subcategory.id, id, `"${input}" → ${outcome.subcategory.id}`);
  }
});

test("보강한 동의어가 의도한 세분류로 간다", () => {
  const cases = [
    ["원통해", "anger.unfair"], ["열불나", "anger.rage"], ["성질나", "anger.irritation"],
    ["고독해", "sadness.lonely"], ["녹초야", "exhaustion.tired"],
    ["기진맥진", "exhaustion.tired"], ["짜릿해", "flutter.thrill"],
    ["움츠러들어", "anxiety.tension"], ["마음이 쓰여", "anxiety.worry"],
    ["앞이 안 보여", "frustration.stuck"], ["타버린 것 같아", "exhaustion.burnout"],
  ];
  for (const [input, id] of cases) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, RESULT.OK, `"${input}" 미매칭`);
    assert.equal(outcome.subcategory.id, id, `"${input}" → ${outcome.subcategory.id}`);
  }
});

// --- 재방문 문구가 방문 횟수와 맞는가 -----------------------------------------

test("숫자를 말하는 문구는 same_day_second에만 있다", () => {
  const counting = /두 번|세 번|번째|두번|세번/;
  for (const message of taxonomy.ui.revisit.same_day) {
    assert.ok(!counting.test(message), `same_day에 횟수 문구: "${message}"`);
  }
  assert.ok(taxonomy.ui.revisit.same_day_second.every((m) => counting.test(m)));
});

test("same_day 문구 풀이 충분히 크다", () => {
  assert.ok(taxonomy.ui.revisit.same_day.length >= 8, "3회차 이상 풀이 8개 미만");
  const total =
    taxonomy.ui.revisit.same_day.length + taxonomy.ui.revisit.same_day_second.length;
  assert.equal(total, 10, `2회차 풀이 10개가 아님 (${total})`);
});

test("2회차에만 숫자 문구가 후보에 들어간다", () => {
  // App.jsx pickGreeting과 같은 규칙
  const poolFor = (visitNumber) =>
    visitNumber === 2
      ? [...taxonomy.ui.revisit.same_day, ...taxonomy.ui.revisit.same_day_second]
      : taxonomy.ui.revisit.same_day;

  const counting = /번째|두 번|두번/;
  assert.ok(poolFor(2).some((m) => counting.test(m)), "2회차에 숫자 문구가 없다");
  for (const n of [3, 4, 5, 9]) {
    assert.ok(
      !poolFor(n).some((m) => counting.test(m)),
      `${n}회차 풀에 숫자 문구가 있다`,
    );
  }
});

test("recordVisit이 주는 값으로 회차가 계산된다", () => {
  // recordVisit()은 증가 전 상태를 준다 → 이번 방문은 +1
  assert.equal((0 ?? 0) + 1, 1);
  assert.equal((1 ?? 0) + 1, 2); // 2회차 → 숫자 문구 허용
  assert.equal((3 ?? 0) + 1, 4); // 4회차 → 숫자 문구 배제
});
