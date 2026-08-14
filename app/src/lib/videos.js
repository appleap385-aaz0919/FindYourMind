/**
 * videos.json 접근 — 일반 카테고리와 위기 풀을 읽는 유일한 지점.
 *
 * ⚠ 이 파일의 존재 이유는 격리다.
 *
 *   위기 영상은 최상위 `crisis` 객체에만 있고, `categories` 배열에는 절대 없다
 *   (PLAN.md 4절: "categories를 순회하는 어떤 코드도 위기 영상에 닿을 수 없다").
 *   배치가 빌드 시점에 두 집합이 서로소임을 단언하고, 워크플로도 배포 전에 다시 검증한다.
 *
 *   앱 쪽 규칙: categories를 순회하는 함수와 crisis를 읽는 함수를 한 함수 안에서
 *   섞지 않는다. 아래 두 함수는 서로의 데이터에 접근하지 않으며, 공통 헬퍼도
 *   "영상 배열 → 화면용 배열" 변환 외에는 공유하지 않는다.
 *   화면 노출 개수도 다르다 (일반은 목록 전체, 위기는 4~6개 랜덤).
 */

// 위기 카테고리 노출 개수 — taxonomy.yaml content_policy.framing
// "노출 개수 4~6개로 제한(선택 부담 최소화)"
const CRISIS_MIN_SHOWN = 4;
const CRISIS_MAX_SHOWN = 6;

/** 세분류 id로 일반 카테고리 영상을 얻는다. crisis에는 접근하지 않는다. */
export function getCategoryVideos(data, subcategoryId) {
  if (!data || !Array.isArray(data.categories)) return [];
  const found = data.categories.find((c) => c.id === subcategoryId);
  return found && Array.isArray(found.videos) ? found.videos : [];
}

/**
 * 위기 카테고리 영상을 얻는다. data.crisis만 읽는다.
 *
 * 매 방문마다 풀에서 4~6개를 랜덤으로 고른다 — 같은 영상이 고정되지 않게 하려는 것이다
 * (taxonomy.yaml framing: "매 방문 시 확보된 풀에서 랜덤 노출").
 */
export function getCrisisVideos(data) {
  const pool = data?.crisis?.videos;
  if (!Array.isArray(pool) || pool.length === 0) return [];

  const count = Math.min(
    pool.length,
    CRISIS_MIN_SHOWN +
      Math.floor(Math.random() * (CRISIS_MAX_SHOWN - CRISIS_MIN_SHOWN + 1)),
  );
  return shuffle(pool).slice(0, count);
}

/** 위기 풀의 신선도. 오래 멈춰 있으면 설정 화면에서 확인할 수 있게 한다. */
export function crisisUpdatedAt(data) {
  return data?.crisis?.updated_at ?? null;
}

export function thumbnailUrl(videoId) {
  return `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;
}

export function watchUrl(videoId) {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

/** ISO 8601 duration → "1:02:03" / "12:30" */
export function formatDuration(iso) {
  if (!iso) return "";
  const match = /^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso);
  if (!match) return "";
  const [, d, h, m, s] = match.map((v) => (v ? Number(v) : 0));
  const total = d * 86400 + h * 3600 + m * 60 + s;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

function shuffle(list) {
  const copy = [...list];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}
