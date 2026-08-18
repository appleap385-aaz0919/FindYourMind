/**
 * 분류 실패 기록 — 개발 중 오분류 사례를 모으기 위한 로컬 전용 장치.
 *
 * ⚠ 기기 밖으로 나가지 않는다.
 *   이 모듈에는 fetch·전송 경로가 없고, 앞으로도 추가하지 않는다.
 *   사용자가 털어놓은 문장은 서버로 보낼 성격의 데이터가 아니다.
 *   (PLAN.md: "데이터는 사용자 디바이스에 경량 저장", 개인정보처리방침에 수집 없음 명시)
 *
 * 무엇을 남기나
 *   - 미매칭(nomatch) 입력 원문, 시각, 어디까지 갔는지(대분류 폴백 여부)
 *   - 최근 50건만. 넘치면 오래된 것부터 버린다.
 *
 * 무엇을 남기지 않나
 *   - 위기(crisis)로 분류된 입력. 가장 민감한 문장이고, 위기 감지는 이미 동작한
 *     것이라 개선 목적의 수집 대상이 아니다.
 *
 * 보는 법
 *   개발자 콘솔에서  await __fym.failures()      목록
 *                   await __fym.status()         재검토 조건 충족 현황
 *                   await __fym.clearFailures()  비우기
 *   설정 화면의 "기록 삭제"로도 함께 지워진다 (settings 스토어를 통째로 비운다).
 *
 * ⛔ 이 숫자는 **어떤 화면에도 표시하지 않는다.** 설정 화면도 포함이다.
 *   마음이 힘들어 들어온 사람에게 "분류 실패 12건"은 보일 이유가 없는 정보이고,
 *   자기 말이 처리되지 못했다는 인상을 준다. 운영자가 콘솔에서만 본다.
 *   (UI에 쓰고 싶어지면 그 요구가 진짜인지 먼저 의심할 것)
 */

import { getSetting, setSetting } from "./db.js";

const KEY = "classification_failures";
const LIMIT = 50;

/**
 * @param {string} input   사용자가 적은 원문
 * @param {string} outcome "nomatch" | "category" — 어디까지 알아들었는지
 */
export async function recordFailure(input, outcome = "nomatch") {
  const text = String(input ?? "").trim();
  if (!text) return;

  const entries = await readFailures();
  entries.unshift({ text, outcome, at: new Date().toISOString() });
  await setSetting(KEY, entries.slice(0, LIMIT));
}

export async function readFailures() {
  const stored = await getSetting(KEY, []);
  return Array.isArray(stored) ? stored : [];
}

export async function clearFailures() {
  await setSetting(KEY, []);
}

/** Phase 2 재검토 조건 1 — 실사용 미분류 누적치 (taxonomy.yaml [결정 기록] Phase 2) */
const PHASE2_MIN_NOMATCH = 30;

/**
 * 재검토 조건 충족 현황.
 *
 * 왜 필요한가
 *   보류 결정 세 개가 전부 "실패 기록이 쌓이면"을 조건으로 두는데, 그 기록을
 *   볼 방법이 콘솔뿐이라 조건이 찼는지 아무도 모르는 상태였다.
 *
 * ⛔ 반환값을 화면에 그리지 말 것. 모듈 상단 주석 참조.
 */
export async function reviewStatus() {
  return summarize(await readFailures());
}

/**
 * 집계는 저장소와 분리해 둔다 — IndexedDB 없이 테스트할 수 있어야 한다.
 *
 * @param {Array<{outcome?: string}>} entries
 */
export function summarize(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const nomatch = list.filter((e) => e?.outcome === "nomatch").length;
  const category = list.filter((e) => e?.outcome === "category").length;

  return {
    total: list.length,
    nomatch,
    category,
    limit: LIMIT,
    phase2ConditionOne: {
      need: PHASE2_MIN_NOMATCH,
      have: nomatch,
      met: nomatch >= PHASE2_MIN_NOMATCH,
    },
    entries: list,
  };
}

/**
 * 콘솔 출력. 사람이 읽을 형태로 정리하고, 판단에 필요한 맥락을 함께 낸다.
 *
 * 유형 분류(A 신체 환유인지 D 모호인지)는 **사람이 한다.** 여기서 자동으로
 * 가르지 않는다 — 그 판단이 Phase 2 착수 여부를 가르는 핵심이라, 기계가
 * 어림잡아 내놓으면 근거 없는 숫자가 결정에 쓰인다.
 */
export async function printStatus() {
  const s = await reviewStatus();

  console.info(
    `[FindYourMind] 분류 실패 누적 ${s.total}건 ` +
      `(미분류 ${s.nomatch} / 대분류까지만 ${s.category}) — 최근 ${s.limit}건만 보관`,
  );

  const one = s.phase2ConditionOne;
  console.info(
    one.met
      ? `조건 1 충족: 미분류 ${one.have}건 ≥ ${one.need}건. ` +
          `다음은 조건 2 — 이 중 절반 이상이 유형 A(신체 환유)인지 사람이 본다.`
      : `조건 1 미충족: 미분류 ${one.have}건 / ${one.need}건 필요 (${one.need - one.have}건 남음).`,
  );

  console.info(
    [
      "",
      "재검토 조건 — 결정 세 개가 이 기록을 조건으로 둔다",
      "",
      "1) Phase 2 온디바이스 모델   → taxonomy.yaml [결정 기록] Phase 2 / PLAN.md Phase 2",
      "     (1) 실사용 미분류 30건 이상          ← 이 화면에서 확인",
      "     (2) 그중 절반 이상이 유형 A(신체 환유)  ← 사람이 분류",
      "     (3) 후보 모델 실측 5MB 이하           ← 별도 측정",
      "     셋 다 충족해야 착수한다. 하나라도 미달이면 보류 유지.",
      "",
      "2) 수치심 대분류             → taxonomy.yaml [결정 기록] 수치심",
      "     미분류 목록에 '쪽팔려·미안해·자책' 계열이 유의미하게 쌓이면",
      "     그때 검색어 실측부터 시작한다.",
      "",
      "3) '끝내고싶' 오탐           → taxonomy.yaml safety [전수 점검] 주석",
      "     ⚠ 이 기록으로는 확인할 수 없다. 위기로 분류된 입력은 일부러",
      "       남기지 않기 때문이다(가장 민감한 문장이라). 업무 문맥 오탐은",
      "       사용자 제보로만 들어온다 — 기다린다고 여기 쌓이지 않는다.",
      "",
      "목록: await __fym.failures()",
    ].join("\n"),
  );

  return s;
}

/**
 * 앱 시작 시 한 줄. **조건이 충족됐을 때만** 출력한다.
 *
 * 평소에 아무것도 찍지 않는 것이 중요하다 — 매번 나오는 로그는 곧 배경이 되고,
 * 정작 조건이 찼을 때도 눈에 띄지 않는다.
 */
export async function announceIfReviewDue() {
  try {
    const { phase2ConditionOne: one } = await reviewStatus();
    if (!one.met) return false;
    console.info(
      `[FindYourMind] Phase 2 재검토 조건 1 충족 — 미분류 ${one.have}건 ≥ ${one.need}건. ` +
        `__fym.status()로 나머지 조건을 확인하세요.`,
    );
    return true;
  } catch {
    // 기록을 못 읽어도 앱 동작에 영향이 없어야 한다. 조용히 넘긴다.
    return false;
  }
}

/**
 * 콘솔에서 바로 확인할 수 있게 window에 붙인다.
 * 개발 중 직접 들여다보는 용도이므로 프로덕션 빌드에서도 남겨둔다 —
 * 읽기 전용이고 로컬 데이터만 보여주므로 노출 위험이 없다.
 */
export function exposeConsoleApi() {
  if (typeof window === "undefined") return;
  window.__fym = {
    failures: async () => {
      const entries = await readFailures();
      // 표로 보는 편이 훑기 좋다.
      if (entries.length && console.table) console.table(entries);
      return entries;
    },
    status: printStatus,
    clearFailures,
  };
}
