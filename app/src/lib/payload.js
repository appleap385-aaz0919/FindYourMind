/**
 * 받은 videos.json이 온전한지 판정한다.
 *
 * 이 판정이 캐시 교체의 유일한 관문이다 (PLAN.md: "완전히 받은 뒤에만 캐시 교체").
 * 다운로드가 중간에 끊겨 잘린 JSON이 들어오거나, 배포 경로가 어긋나
 * 부분 실행 산출물(videos.partial.json)이 올라온 경우를 여기서 막는다.
 * 한 번 캐시에 들어가면 다음 실행부터 계속 그걸 쓰기 때문에 들어가기 전에 걸러야 한다.
 *
 * 의존성이 없는 별도 모듈인 이유: sync.js는 시드 JSON과 IndexedDB를 import해서
 * 브라우저 밖에서 로드되지 않는다. 이 관문만은 테스트로 직접 검증할 수 있어야 한다.
 */
export function isCompleteVideosPayload(payload) {
  if (!payload || typeof payload !== "object") return false;
  if (payload.partial === true) return false;
  if (typeof payload.version !== "string") return false;
  if (!Array.isArray(payload.categories) || payload.categories.length === 0) {
    return false;
  }
  if (!payload.crisis || !Array.isArray(payload.crisis.videos)) return false;
  return payload.categories.every(
    (c) => c && typeof c.id === "string" && Array.isArray(c.videos),
  );
}
