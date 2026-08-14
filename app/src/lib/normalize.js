/**
 * 입력 정규화 — scripts/lib/normalize.py와 문자 단위로 같은 결과를 내야 한다.
 *
 * 왜 같아야 하나:
 *   배치는 이 규칙으로 blocklist를 적용하고, 앱은 같은 규칙으로 위기 키워드와
 *   감정 키워드를 매칭한다. 두 구현이 어긋나면 배치가 거른 표현을 앱이 통과시키거나
 *   그 반대가 된다. taxonomy.yaml normalization.steps가 단일 소스다.
 *
 * 프로토타입 코드를 그대로 쓰지 않은 이유:
 *   emotion-prototype.jsx는 /[^\w가-힣ㄱ-ㅎㅏ-ㅣa-z0-9]/g 를 썼는데,
 *   JS의 \w는 [A-Za-z0-9_]뿐이라 Python의 \w(유니코드 전체 문자)보다 훨씬 좁다.
 *   한글만 있는 입력에서는 결과가 같지만 한자·가나·악센트 문자가 섞이면 갈린다.
 *   Python의 \w에 대응시키려면 유니코드 속성 이스케이프가 필요하다.
 *
 *   Python  re: \w == 유니코드 단어 문자 + '_'
 *   JS     대응: \p{L}(문자) + \p{N}(숫자) + '_'  ※ u 플래그 필수
 *
 *   패턴에 남아 있던 가-힣·ㄱ-ㅎ·ㅏ-ㅣ·a-z0-9는 \p{L}\p{N}에 이미 포함되므로 뺐다.
 *   (한글 자모 ㄱ-ㅎ, ㅏ-ㅣ는 유니코드 카테고리 Lo라 \p{L}에 들어온다)
 */

const NON_WORD = /[^\p{L}\p{N}_]/gu;
const REPEATS = /(.)\1{2,}/gu;

/** 비교용 정규화 문자열을 반환한다. */
export function normalize(text) {
  if (!text) return "";
  return text
    .toLowerCase()
    .replace(NON_WORD, "")
    .replace(REPEATS, "$1$1")
    .replace(/ㅜ/gu, "ㅠ");
}

/**
 * haystack(원문)에 포함된 terms를 정규화 기준으로 찾아 반환한다.
 * 걸러낸 이유를 남길 수 있도록 불리언이 아니라 목록을 준다.
 */
export function matchedTerms(haystack, terms) {
  const normalized = normalize(haystack);
  if (!normalized) return [];
  const hits = [];
  for (const term of terms) {
    const needle = normalize(term);
    if (needle && normalized.includes(needle)) hits.push(term);
  }
  return hits;
}

/** terms 중 하나라도 포함되면 true (조기 종료). */
export function containsAny(haystack, terms) {
  const normalized = normalize(haystack);
  if (!normalized) return false;
  return terms.some((t) => {
    const needle = normalize(t);
    return needle && normalized.includes(needle);
  });
}
