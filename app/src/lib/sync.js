/**
 * 데이터 갱신 — PLAN.md Phase 3 "데이터 갱신·오프라인 정책" 표 그대로.
 *
 * 핵심 원칙 세 가지:
 *   1. UI를 막지 않는다. 화면은 캐시(없으면 번들 시드)로 즉시 그리고 갱신은 뒤에서.
 *   2. 완전히 받은 뒤에만 캐시를 교체한다. 중간에 끊기면 기존 캐시를 그대로 둔다.
 *   3. 배경 갱신 실패는 사용자에게 알리지 않는다 ("연결 실패" 배너 금지).
 *      그래서 이 모듈의 모든 실패 경로는 조용히 false를 돌려준다.
 */

import seed from "../data/seed-videos.json";
import { isCompleteVideosPayload } from "./payload.js";
import {
  KEYS,
  clearVideosCache,
  getSetting,
  readVideosCache,
  setSetting,
  writeVideosCache,
} from "./db.js";

const DATA_BASE = __DATA_BASE__;

const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000; // 6시간 (PLAN.md)
const MAX_CACHE_AGE_MS = 30 * 24 * 60 * 60 * 1000; // 30일 — YouTube API 약관
const FETCH_TIMEOUT_MS = 20_000;

/** 번들에 포함된 최초 실행용 시드. 네트워크도 캐시도 없을 때의 바닥. */
export function seedData() {
  return seed;
}

/**
 * 화면을 그리는 데 쓸 데이터를 즉시 돌려준다 (네트워크 대기 없음).
 *
 * 캐시가 30일을 넘으면 폐기하고 시드로 돌아간다. 오래된 메타데이터를 계속
 * 노출하지 않기 위한 약관 요구사항이며, 이건 조용히 처리한다.
 */
export async function loadInitialData() {
  const cached = await readVideosCache();
  if (!cached?.data) return { data: seed, source: "seed" };

  const age = Date.now() - new Date(cached.receivedAt).getTime();
  if (!Number.isFinite(age) || age > MAX_CACHE_AGE_MS) {
    await clearVideosCache();
    return { data: seed, source: "seed" };
  }
  return { data: cached.data, source: "cache", receivedAt: cached.receivedAt };
}

/**
 * 갱신이 필요한지 판단한다 — 마지막 확인이 6시간을 넘었는가.
 * PWA에는 크론이 없으므로 "앱을 열 때" 확인하는 것이 유일한 시점이다.
 */
export async function shouldCheck(now = Date.now()) {
  const last = await getSetting(KEYS.LAST_CHECKED_AT, null);
  if (!last) return true;
  const elapsed = now - new Date(last).getTime();
  return !Number.isFinite(elapsed) || elapsed > CHECK_INTERVAL_MS;
}

/**
 * 백그라운드 갱신. UI를 막지 않는 자리에서 호출한다.
 *
 * @param {string|null} currentVersion 지금 화면이 쓰고 있는 데이터의 version
 * @returns {Promise<{updated: boolean, data?: object}>}
 *          updated=true여도 **보고 있는 화면은 바꾸지 않는다** (PLAN.md).
 *          호출자는 다음 입력부터 새 데이터를 쓰면 된다.
 */
export async function syncInBackground(currentVersion) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return { updated: false };
  }

  try {
    // 1) 수십 바이트짜리 version.json만 먼저 받는다.
    const remote = await fetchJson(`${DATA_BASE}version.json?t=${Date.now()}`);
    await setSetting(KEYS.LAST_CHECKED_AT, new Date().toISOString());

    if (!remote?.version || remote.version === currentVersion) {
      return { updated: false };
    }

    // 2) 바뀐 경우에만 본체를 받는다.
    //    GitHub Pages는 캐시 헤더를 제어할 수 없어 ?v={version}으로 무효화한다.
    const fresh = await fetchJson(
      `${DATA_BASE}videos.json?v=${encodeURIComponent(remote.version)}`,
    );

    // 3) 온전한 응답인지 확인한 뒤에만 캐시를 교체한다.
    //    중간에 끊긴 부분 데이터가 캐시로 들어가면 다음 실행부터 계속 그걸 쓴다.
    if (!isCompleteVideosPayload(fresh)) return { updated: false };

    await writeVideosCache(fresh);
    return { updated: true, data: fresh };
  } catch {
    // 조용히 포기한다. 화면에는 아무것도 띄우지 않는다.
    return { updated: false };
  }
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(String(response.status));
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

export const __test__ = { CHECK_INTERVAL_MS, MAX_CACHE_AGE_MS };
