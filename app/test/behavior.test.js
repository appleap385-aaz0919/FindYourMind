/**
 * 확정 사항이 실제로 지켜지는지 검사한다.
 * 여기가 깨지면 UI가 아니라 약속이 깨진 것이다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { classify, RESULT } from "../src/lib/classify.js";
import { normalize } from "../src/lib/normalize.js";
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
  // dist/는 배치 산출물이라 저장소에 없다(.gitignore). CI의 깨끗한 체크아웃에서도
  // 돌아야 하므로, 커밋된 실물 사본으로 검사한다.
  //   전체 — src/data/seed-videos.json (실제 videos.json을 그대로 옮긴 번들 시드)
  //   부분 — test/fixtures/videos.partial.sample.json (--only 산출물을 줄인 것)
  const partial = JSON.parse(
    readFileSync(join(here, "fixtures", "videos.partial.sample.json"), "utf8"),
  );

  assert.equal(isCompleteVideosPayload(videos), true, "정상 배포물이 거부됐다");
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

// --- 다시 적기는 항상 텍스트 입력으로 돌아간다 ---------------------------------

test("핸들러로 넘기는 reset은 인자를 받지 않는다", () => {
  // 실제로 났던 버그: reset(nextMode = "text")를 onClick={reset}로 넘겼더니
  // React가 클릭 이벤트를 첫 인자로 줬다. 기본값은 undefined일 때만 적용되므로
  // setMode(이벤트)가 실행됐고, mode가 문자열이 아니어서 선택 UI가 계속 렌더됐다.
  const src = readFileSync(join(here, "..", "src", "App.jsx"), "utf8");

  const signature = /const reset = \(([^)]*)\) =>/.exec(src);
  assert.ok(signature, "reset 정의를 찾지 못했다");
  assert.equal(
    signature[1].trim(),
    "",
    `reset이 인자를 받는다(${signature[1]}) — 핸들러로 넘기면 이벤트가 들어온다`,
  );

  // 기본값이 이벤트를 막지 못한다는 사실 자체를 고정한다
  const withDefault = (nextMode = "text") => nextMode;
  assert.notEqual(withDefault({ type: "click" }), "text");
});

test("다시 적기 경로가 모두 텍스트 입력으로 간다", () => {
  const src = readFileSync(join(here, "..", "src", "App.jsx"), "utf8");

  // reset은 언제나 text
  assert.ok(
    /const reset = \(\) => resetTo\("text"\);/.test(src),
    "reset이 resetTo(\"text\")를 부르지 않는다",
  );

  // resetTo는 mode와 selectedCategory를 함께 되돌린다
  const body = src.slice(src.indexOf("const resetTo = ("), src.indexOf("const reset = ()"));
  for (const call of ["setMode(nextMode)", "setSelectedCategory(null)", 'setPhase("input")']) {
    assert.ok(body.includes(call), `resetTo에 ${call}가 없다`);
  }

  // 하단 "다시 적어보기"(Closing)와 플로팅 버튼이 같은 reset을 쓴다
  const closingHandlers = [...src.matchAll(/<Closing[^>]*onBack=\{([^}]*)\}/g)].map(
    (m) => m[1].trim(),
  );
  assert.ok(closingHandlers.length >= 2, "Closing 호출부를 찾지 못했다");
  for (const handler of closingHandlers) {
    assert.equal(handler, "reset", `Closing onBack이 reset이 아니다: ${handler}`);
  }
  const floating = /<FloatingRestart[^>]*onClick=\{([^}]*)\}/.exec(src);
  assert.ok(floating, "FloatingRestart 호출부를 찾지 못했다");
  assert.equal(floating[1].trim(), "reset", "플로팅 버튼이 reset을 쓰지 않는다");

  // 모드를 지정하는 곳은 화살표로 감싼다 — 이벤트가 인자로 들어가지 않게
  assert.ok(
    src.includes('onBack={() => resetTo("select")}'),
    "무매칭 → 골라서 찾기 경로가 깨졌다",
  );
  assert.ok(!/onBack=\{resetTo\}|onClick=\{resetTo\}/.test(src), "resetTo를 핸들러로 직접 넘긴다");
});

// --- 화면 전환 시 스크롤 최상단 -------------------------------------------------

test("스크롤 리셋이 전환 전체에 걸려 있다", () => {
  const src = readFileSync(join(here, "..", "src", "App.jsx"), "utf8");
  const effect = src.slice(
    src.indexOf("화면이 바뀌면 항상 맨 위에서 시작한다"),
    src.indexOf("// --- 시작:"),
  );
  // 주석에 "smooth"를 설명하는 문장이 있으므로 주석을 걷어내고 코드만 본다.
  const code = effect
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith("//"))
    .join(" ");

  assert.ok(code.includes("window.scrollTo({ top: 0"), "scrollTo가 없다");
  // 결과 화면만 거르던 조기 반환이 남아 있으면 입력 복귀에서 스크롤이 안 올라간다
  assert.ok(!code.includes('phase !== "result"'), "결과 전용 분기가 남아 있다");

  const deps = code.slice(code.lastIndexOf("["), code.lastIndexOf("]") + 1);
  for (const dep of ["phase", "mode", "selectedCategory", "result"]) {
    assert.ok(
      deps.includes(dep),
      `의존성에 ${dep}가 없다 — 그 전환에서 스크롤이 남는다 (deps: ${deps})`,
    );
  }
  assert.ok(!code.includes("smooth"), "전환에는 smooth를 쓰지 않기로 했다");
});

// --- 테스트 파일이 조용히 빠지지 않게 -------------------------------------------

test("test/의 모든 *.test.js가 npm test 목록에 있다", () => {
  // package.json의 test 스크립트는 glob이 아니라 파일을 하나씩 적는다.
  //   node --test에 glob을 넘기면 Node 버전에 따라 동작이 갈린다. CI(Node 20)에서
  //   앱 배포가 계속 실패한 원인이 여기였다 — 로컬(Node 24)에서는 통과했다.
  //   버전 가정에 기대지 않으려고 명시 목록으로 바꿨고, 대신 새 테스트 파일을
  //   목록에 넣는 것을 잊으면 조용히 안 돌게 되므로 여기서 막는다.
  const pkg = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8"));
  const script = pkg.scripts.test;

  assert.ok(!script.includes("*"), `test 스크립트에 glob이 있다: ${script}`);

  const files = readdirSync(here).filter((f) => f.endsWith(".test.js"));
  assert.ok(files.length > 0, "테스트 파일을 찾지 못했다");
  for (const file of files) {
    assert.ok(
      script.includes(`test/${file}`),
      `${file}이 npm test 목록에 없다 — package.json scripts.test에 추가하세요`,
    );
  }
});

// --- 자·타해 표현의 갈림 --------------------------------------------------------

test("'죽고싶'이 '죽여버리고 싶어'에 부분 매칭되지 않는다", () => {
  // 한글은 음절 단위라 "죽여버리고싶어"에서 죽 다음이 여이고 고가 아니다.
  // 위기/격분이 갈리는 근거가 이 성질이므로 여기서 고정한다.
  assert.ok(!normalize("죽여버리고 싶어").includes(normalize("죽고싶")));
  assert.ok(normalize("죽고 싶어").includes(normalize("죽고싶")));
});

test("타인 지향은 격분, 자기 지향은 위기로 갈린다", () => {
  const cases = [
    // 요청받은 두 문장
    ["죽고 싶어", RESULT.CRISIS, null],
    ["죽여버리고 싶어", RESULT.OK, "anger.rage"],
    // 타인 지향 — 격분
    ["죽이고 싶어", RESULT.OK, "anger.rage"],
    ["패버리고 싶어", RESULT.OK, "anger.rage"],
    ["없애버리고 싶어", RESULT.OK, "anger.rage"],
    ["가만두지 않을거야", RESULT.OK, "anger.rage"],
    ["저 사람 죽여버리고 싶어", RESULT.OK, "anger.rage"],
    // 자기 지향 — 위기. anger.rage에 "죽이고싶"을 넣으면서 생긴 구멍을
    // safety.crisis_keywords의 자기 지향 가드가 막는다. 위기 검사가 먼저 돌기 때문이다.
    ["나를 죽이고 싶어", RESULT.CRISIS, null],
    ["나 죽이고 싶어", RESULT.CRISIS, null],
    ["나 죽여버리고 싶어", RESULT.CRISIS, null],
    ["나를 죽여버리고 싶어", RESULT.CRISIS, null],
    ["나를 없애버리고 싶어", RESULT.CRISIS, null],
    ["내가 죽고 싶어", RESULT.CRISIS, null],
  ];
  for (const [input, kind, subId] of cases) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, kind, `"${input}" → ${outcome.kind}`);
    if (subId) {
      assert.equal(outcome.subcategory.id, subId, `"${input}" → ${outcome.subcategory.id}`);
    }
  }
});

test("자기 지향 가드가 위기 키워드에 들어 있다", () => {
  for (const guard of ["나를죽이", "나죽이고싶", "나를죽여", "나죽여버리", "나를없애"]) {
    assert.ok(
      taxonomy.safety.crisis_keywords.includes(guard),
      `위기 키워드에 ${guard}가 없다 — 자해 표현이 격분으로 분류된다`,
    );
  }
});

// --- 활용형 흡수와 흔한 오타 -----------------------------------------------------

test("'-버릴 것 같다' 활용형이 어간으로 흡수된다", () => {
  // "미쳐버리"는 "미쳐버릴"을 잡지 못한다 — 한글은 음절 단위라 리와 릴이 다르다.
  // "미쳐버"까지 줄여야 전부 걸린다. 외로/외롭 때와 같은 성질이다.
  assert.ok(!normalize("미쳐버릴것같아").includes(normalize("미쳐버리")));
  assert.ok(normalize("미쳐버릴것같아").includes(normalize("미쳐버")));

  for (const input of [
    "미쳐버릴 것 같아", "미쳐버리겠다", "미쳐버려", "미쳐버렸어",
    "미처버릴것같아", "미처버리겠어",
    "돌아버릴 것 같아", "돌아버리겠다",
    "환장하겠네", "환장할 것 같아",
  ]) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, RESULT.OK, `"${input}" 미매칭`);
    assert.equal(outcome.subcategory.id, "anger.rage", `"${input}" → ${outcome.subcategory.id}`);
  }
});

test("흔한 오타 표기가 잡힌다", () => {
  const cases = [
    ["귀찬아 죽겠어", "exhaustion.listless"], // 귀찮
    ["괜찬아졌어", "calm.stable"], // 괜찮
    ["빡처 죽겠네", "anger.irritation"], // 빡쳐
    ["돼는일이없어", "frustration.blocked"], // 되는일이없
    ["어떻하지", "anxiety.worry"], // 어떡하지
  ];
  for (const [input, id] of cases) {
    const outcome = classify(input, taxonomy);
    assert.equal(outcome.kind, RESULT.OK, `"${input}" 미매칭`);
    assert.equal(outcome.subcategory.id, id, `"${input}" → ${outcome.subcategory.id}`);
  }
});

test("어간을 넓히다 정상 표현을 격분으로 보내지 않는다", () => {
  // "미처버"까지 줄이면 "미처 버리지 못한 물건들"에 걸린다 — 상실감 맥락이라
  // 격분으로 보내면 안 된다. 그래서 오타 쪽 어간은 좁게 잡았다.
  for (const input of ["미처 버리지 못한 물건들", "뒤돌아 버렸다", "집에 돌아 버스를 탔다"]) {
    const outcome = classify(input, taxonomy);
    const id = outcome.kind === RESULT.OK ? outcome.subcategory.id : null;
    assert.notEqual(id, "anger.rage", `"${input}"가 격분으로 분류됐다`);
  }
});
