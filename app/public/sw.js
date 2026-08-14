/* eslint-env serviceworker */
/**
 * Service worker — 앱 셸 캐시 + 유튜브 썸네일 LRU.
 *
 * PLAN.md Phase 3 "오프라인 대응 설계 1":
 *   img.youtube.com 응답을 cache-first로 저장 (최근 200개, LRU).
 *   한 번 본 영상은 오프라인에서도 목록이 온전히 보인다.
 *
 * 데이터(videos.json/version.json)는 여기서 캐시하지 않는다.
 * 갱신·폐기 규칙(6시간 확인, 30일 만료, 원자적 교체)이 앱 쪽 sync.js에 있고,
 * service worker가 따로 캐시하면 두 곳이 서로 다른 사본을 들고 어긋난다.
 */

const VERSION = "v1";
const SHELL_CACHE = `fym-shell-${VERSION}`;
const THUMB_CACHE = `fym-thumbs-${VERSION}`;

const THUMB_HOST = "img.youtube.com";
const THUMB_LIMIT = 200; // 최근 200개 (PLAN.md)

self.addEventListener("install", (event) => {
  // 앱 셸은 fetch 시점에 채운다(빌드 산출물 파일명이 해시라 목록을 미리 못 박는다).
  // 새 버전이 곧바로 뜨도록 대기를 건너뛴다.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith("fym-") && !name.endsWith(VERSION))
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // --- 유튜브 썸네일: cache-first + LRU -------------------------------------
  if (url.hostname === THUMB_HOST) {
    event.respondWith(thumbnailFirst(request));
    return;
  }

  // --- 데이터: service worker가 관여하지 않는다 -----------------------------
  if (url.pathname.includes("/data/")) return;

  // --- 앱 셸: 같은 오리진만 network-first, 실패 시 캐시 ----------------------
  if (url.origin === self.location.origin) {
    event.respondWith(shellWithFallback(request));
  }
});

/**
 * 썸네일은 한 번 받으면 바뀌지 않으므로 캐시를 먼저 본다.
 * 캐시에 있으면 네트워크를 아예 건드리지 않아 오프라인에서도 그대로 보인다.
 */
async function thumbnailFirst(request) {
  const cache = await caches.open(THUMB_CACHE);
  const hit = await cache.match(request);
  if (hit) {
    void touch(cache, request, hit); // LRU 최근 사용으로 올린다
    return hit;
  }

  try {
    const response = await fetch(request);
    // 404(삭제된 영상)는 캐시하지 않는다. 나중에 되살아날 수도 있고,
    // 무엇보다 앱이 onError로 카드를 숨기는 판단을 매번 새로 해야 한다.
    if (response.ok) {
      await cache.put(request, response.clone());
      void enforceLimit(cache);
    }
    return response;
  } catch (error) {
    return new Response("", { status: 504, statusText: "offline" });
  }
}

/**
 * LRU 갱신 — Cache Storage에는 접근 시각이 없어서, 재삽입으로 순서를 만든다.
 * cache.keys()가 삽입 순서를 보존하므로 다시 넣으면 맨 뒤로 간다.
 */
async function touch(cache, request, response) {
  try {
    await cache.delete(request);
    await cache.put(request, response.clone());
  } catch {
    /* 캐시 조작 실패는 무시한다 — 썸네일 하나 못 캐시할 뿐이다 */
  }
}

async function enforceLimit(cache) {
  try {
    const keys = await cache.keys();
    const excess = keys.length - THUMB_LIMIT;
    if (excess <= 0) return;
    // 앞쪽이 가장 오래 안 쓰인 것이다.
    await Promise.all(keys.slice(0, excess).map((key) => cache.delete(key)));
  } catch {
    /* 무시 */
  }
}

/**
 * 앱 셸은 network-first다. 배포 직후 낡은 셸이 고정되는 것을 막기 위해서다.
 * 오프라인이면 캐시로, 그마저 없고 문서 요청이면 index.html로 떨어진다(SPA).
 */
async function shellWithFallback(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const hit = await cache.match(request);
    if (hit) return hit;
    if (request.mode === "navigate") {
      const index = await cache.match(`${self.location.pathname.replace(/sw\.js$/, "")}index.html`);
      if (index) return index;
    }
    throw error;
  }
}
