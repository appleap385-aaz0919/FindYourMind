/**
 * 문구 회전 — "직전에 보여준 것은 제외하고 랜덤".
 *
 * taxonomy.yaml meta.message_rotation_rule:
 *   empathy_messages / closing_messages / ui.placeholders는 매번 랜덤 1개.
 *   단 해당 세분류에서 직전에 보여준 문구는 제외한다.
 *   empathy_messages는 사용자가 마음을 털어놓은 직후 처음 마주하는 문장이라
 *   반복이 가장 크게 체감되는 지점이므로 회전이 특히 중요하다.
 *   (구현: 세분류별 마지막 표시 인덱스를 IndexedDB settings에 저장)
 *
 * 프로토타입은 useRef에 두어 새로고침하면 잊었다. 여기서는 IndexedDB에 남겨
 * 다시 방문해도 직전 문구가 곧바로 또 나오지 않는다.
 */

import { KEYS, getSetting, setSetting } from "./db.js";

// 세션 동안의 인덱스 캐시. 매 표시마다 IndexedDB를 기다리지 않기 위한 것으로,
// 저장은 뒤에서 비동기로 따라간다 (문구 표시가 저장을 기다릴 이유가 없다).
let indexes = {};
let loaded = false;

export async function loadMessageIndexes() {
  if (loaded) return;
  const stored = await getSetting(KEYS.MESSAGE_INDEXES, {});
  indexes = stored && typeof stored === "object" ? stored : {};
  loaded = true;
}

/**
 * 직전 인덱스를 제외하고 하나 고른다.
 *
 * @param {string} slot 회전 단위 키 (예: "empathy:anxiety.restless", "placeholder")
 * @param {string[]} items
 * @returns {string}
 */
export function pickMessage(slot, items) {
  if (!Array.isArray(items) || items.length === 0) return "";
  if (items.length === 1) return items[0];

  const previous = indexes[slot];
  // 직전 것을 뺀 나머지에서 고른다. do-while로 재추첨하지 않는 이유:
  // 후보가 2개일 때 재추첨은 평균 2회 도는데, 그냥 빼고 고르면 한 번에 끝난다.
  const candidates = [];
  for (let i = 0; i < items.length; i += 1) {
    if (i !== previous) candidates.push(i);
  }
  const chosen = candidates[Math.floor(Math.random() * candidates.length)];

  indexes[slot] = chosen;
  void persist();
  return items[chosen];
}

let pending = null;
function persist() {
  // 연속 호출(공감 문구 + 마무리 문구)을 한 번의 쓰기로 묶는다.
  if (pending) return pending;
  pending = Promise.resolve().then(async () => {
    pending = null;
    await setSetting(KEYS.MESSAGE_INDEXES, indexes);
  });
  return pending;
}

/** 디바이스 시계만 사용한다. 위치정보는 쓰지 않는다. */
export function greetingSlot(date = new Date()) {
  const hour = date.getHours();
  if (hour < 6) return "night";
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

/**
 * 방문 간격 판정 — taxonomy.yaml ui.revisit.logic
 *
 * 기록이 없으면(시크릿 모드·데이터 삭제·다른 기기) first_visit이다.
 * 이건 오작동이 아니라 정상 동작이며, 어떤 경우에도 "왜 안 왔냐"는 문구를 쓰지 않는다.
 */
export function revisitSlot({ lastVisitAt, visitCountToday }, now = new Date()) {
  if (!lastVisitAt) return "first_visit";

  const last = new Date(lastVisitAt);
  if (Number.isNaN(last.getTime())) return "first_visit";

  const sameLocalDay = last.toDateString() === now.toDateString();
  if (sameLocalDay && (visitCountToday ?? 0) >= 1) return "same_day";

  const days = Math.floor((now - last) / (24 * 60 * 60 * 1000));
  if (days >= 7) return "long_absence";
  if (days >= 1) return "recent";
  return "same_day";
}

/**
 * 이번 방문이 오늘 몇 번째인가.
 *
 * recordVisit()은 갱신 **전** 상태를 주므로 이번 방문을 포함하려면 +1이다.
 * 기록이 없으면(시크릿 모드·데이터 삭제) 1회차로 본다.
 */
export function visitNumberOf({ visitCountToday } = {}) {
  return (visitCountToday ?? 0) + 1;
}

/**
 * same_day 인사 문구 후보 풀.
 *
 * 횟수를 말하는 문구는 **2회차에서만** 쓴다. 3회차 이상에서 "두 번째네요"가
 * 나오면 틀린 숫자를 말하게 되고, 그건 아무 말도 안 하느니만 못하다
 * (taxonomy.yaml ui.revisit 주석 참조).
 *
 * ⚠ App.jsx의 pickGreeting이 이 함수를 부른다. 여기 있는 이유는 테스트가
 *   **실제로 실행되는 코드**를 검사하기 위해서다 — App.jsx는 JSX라 node:test에서
 *   import할 수 없어, 예전에는 테스트가 이 규칙을 베껴 적었다. 그러면 App.jsx가
 *   바뀌어도 테스트는 자기 사본을 검사하며 통과한다(2026-08-17 reset 사건과 같은 유형).
 *   규칙을 고칠 일이 있으면 App.jsx가 아니라 여기서 고친다.
 */
export function sameDayGreetingPool(visit, taxonomy) {
  const { same_day: sameDay, same_day_second: sameDaySecond } = taxonomy.ui.revisit;
  return visitNumberOf(visit) === 2 ? [...sameDay, ...sameDaySecond] : sameDay;
}

/** 방문 기록 갱신. 날짜가 바뀌면 오늘 방문 수를 0으로 되돌린다. */
export async function recordVisit(now = new Date()) {
  const today = now.toDateString();
  const storedDate = await getSetting(KEYS.VISIT_DATE, null);
  const previousCount =
    storedDate === today ? await getSetting(KEYS.VISIT_COUNT_TODAY, 0) : 0;

  const state = {
    lastVisitAt: await getSetting(KEYS.LAST_VISIT_AT, null),
    visitCountToday: previousCount,
  };

  await setSetting(KEYS.VISIT_DATE, today);
  await setSetting(KEYS.VISIT_COUNT_TODAY, previousCount + 1);
  await setSetting(KEYS.LAST_VISIT_AT, now.toISOString());
  return state; // 갱신 *전* 상태 — 인사 문구는 이걸로 고른다
}

export const __test__ = {
  reset() {
    indexes = {};
    loaded = false;
  },
  snapshot: () => ({ ...indexes }),
};
