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
 *                   await __fym.clearFailures()  비우기
 *   설정 화면의 "기록 삭제"로도 함께 지워진다 (settings 스토어를 통째로 비운다).
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
    clearFailures,
  };
}
