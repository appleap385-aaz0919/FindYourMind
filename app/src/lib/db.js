/**
 * IndexedDB (idb) — videos 캐시와 settings.
 *
 * PLAN.md 4절:
 *   videos_cache : videos.json 원본 + 수신 시각
 *   settings     : 마지막 갱신 시각, 방문 기록, 문구 회전 인덱스
 *
 * 저장하는 건 전부 기기 안에만 있다. 서버로 나가는 경로가 코드에 없다.
 */

import { openDB } from "idb";

const DB_NAME = "findyourmind";
const DB_VERSION = 1;

export const STORE_VIDEOS = "videos_cache";
export const STORE_SETTINGS = "settings";

// videos_cache에 저장되는 유일한 키. 통째로 교체하므로 레코드가 하나뿐이다.
const VIDEOS_KEY = "current";

let dbPromise = null;

function db() {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(database) {
        if (!database.objectStoreNames.contains(STORE_VIDEOS)) {
          database.createObjectStore(STORE_VIDEOS);
        }
        if (!database.objectStoreNames.contains(STORE_SETTINGS)) {
          database.createObjectStore(STORE_SETTINGS);
        }
      },
    });
  }
  return dbPromise;
}

/**
 * IndexedDB를 못 쓰는 환경(시크릿 모드 일부, 저장소 차단)에서도 앱은 동작해야 한다.
 * 실패를 예외로 올리지 않고 null/기본값을 돌려준다 — 캐시가 없으면 번들 시드로 산다.
 */
async function safely(operation, fallback) {
  try {
    return await operation();
  } catch {
    return fallback;
  }
}

// --- videos 캐시 -------------------------------------------------------------

export async function readVideosCache() {
  return safely(async () => (await db()).get(STORE_VIDEOS, VIDEOS_KEY), null);
}

/**
 * 캐시를 통째로 교체한다.
 *
 * 호출자는 **완전히 받은 데이터만** 넘겨야 한다 (PLAN.md "완전히 받은 뒤에만 캐시 교체").
 * 부분 응답을 조각조각 쓰지 않도록 이 함수는 병합을 제공하지 않는다.
 */
export async function writeVideosCache(data, receivedAt = new Date()) {
  return safely(async () => {
    await (await db()).put(
      STORE_VIDEOS,
      { data, receivedAt: receivedAt.toISOString() },
      VIDEOS_KEY,
    );
    return true;
  }, false);
}

export async function clearVideosCache() {
  return safely(async () => {
    await (await db()).delete(STORE_VIDEOS, VIDEOS_KEY);
    return true;
  }, false);
}

// --- settings ----------------------------------------------------------------

export async function getSetting(key, fallback = null) {
  return safely(async () => {
    const value = await (await db()).get(STORE_SETTINGS, key);
    return value === undefined ? fallback : value;
  }, fallback);
}

export async function setSetting(key, value) {
  return safely(async () => {
    await (await db()).put(STORE_SETTINGS, value, key);
    return true;
  }, false);
}

/** 설정 화면의 "기록 삭제" — taxonomy.yaml ui.revisit.privacy_note */
export async function clearAllLocalData() {
  return safely(async () => {
    const database = await db();
    await database.clear(STORE_SETTINGS);
    await database.clear(STORE_VIDEOS);
    return true;
  }, false);
}

export const KEYS = {
  LAST_CHECKED_AT: "last_checked_at", // version.json을 마지막으로 확인한 시각
  LAST_VISIT_AT: "last_visit_at",
  VISIT_COUNT_TODAY: "visit_count_today",
  VISIT_DATE: "visit_date",
  LAST_SUBCATEGORY_ID: "last_subcategory_id",
  MESSAGE_INDEXES: "message_indexes", // 직전에 보여준 문구 인덱스 (문구 회전용)
};
