"""taxonomy.yaml 로더 — 단일 소스를 코드가 해석하는 유일한 지점.

여기 없는 정책은 코드 어디에도 없어야 한다.
blocklist 계층, 위기 가드레일, 검색어 로테이션은 모두 이 모듈을 통해서만 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# --- PLAN.md / taxonomy.yaml에서 확정된 수치 ---------------------------------
CATEGORY_MIN_VIDEOS = 15  # 카테고리당 목표 하한 (PLAN.md 4절)
CATEGORY_MAX_VIDEOS = 20  # 카테고리당 목표 상한
CRISIS_MIN_VIDEOS = 12  # 미달 시 필터를 완화하지 않고 직전 결과 유지 (filter_rules)
CRISIS_MAX_VIDEOS = 20
CRISIS_MAX_PER_CHANNEL = 3  # 위기 카테고리 채널당 상한 (content_policy.max_per_channel 기본값)
CRISIS_PER_CHANNEL_STEPS = 3  # 20건을 못 채울 때 상한을 몇 단계까지 올리는가 (3 → 4 → 5)
MIN_DURATION_SECONDS = 180  # 3분 미만 제외 (Shorts는 여기에 포함되어 걸러진다)
MAX_QUERIES_PER_SUBCATEGORY = 3  # 4개 중 3개 로테이션 (쿼터 7,200 유지)
CRISIS_STALE_DAYS = 3  # crisis.updated_at이 이보다 오래되면 경보
EXPECTED_SUBCATEGORIES = 24

NEGATIVE_TIER = "tier_b_negative"
GLOBAL_TIER = "tier_a_global"
CRISIS_TIER = "tier_c_crisis_only"


class TaxonomyError(ValueError):
    """taxonomy.yaml이 배치가 기대하는 구조를 만족하지 않는다."""


@dataclass(frozen=True)
class Subcategory:
    """세분류 1개. index는 검색어 로테이션의 위상을 결정한다."""

    id: str
    parent: str
    label: str
    tone: str
    search_queries: tuple[str, ...]
    index: int


class Taxonomy:
    """taxonomy.yaml 접근자."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.subcategories = _parse_subcategories(raw)
        tiers = _require(raw, "blocklist_tiers")
        self.tier_a = _tier_terms(tiers, GLOBAL_TIER)
        self.tier_b = _tier_terms(tiers, NEGATIVE_TIER)
        self.tier_c = _tier_terms(tiers, CRISIS_TIER)
        self.negative_parents = _parse_negative_parents(raw, tiers)
        self.crisis = _parse_crisis(raw)

    # --- blocklist 계층 -----------------------------------------------------
    def blocklist_for(self, parent_id: str) -> dict[str, tuple[str, ...]]:
        """일반 카테고리에 적용할 계층을 반환한다.

        긍정 감정(기쁨·설렘·평온·심심함)에는 tier_a만 적용한다.
        joy.grateful의 "눈물나는 감동"처럼 그 카테고리에 적합한 콘텐츠를
        tier_b가 잘라내면 손해이기 때문이다 (taxonomy.yaml tier_b rationale).
        """
        tiers: dict[str, tuple[str, ...]] = {GLOBAL_TIER: self.tier_a}
        if parent_id in self.negative_parents:
            tiers[NEGATIVE_TIER] = self.tier_b
        return tiers

    def crisis_blocklist(self) -> dict[str, tuple[str, ...]]:
        """위기 카테고리는 a+b+c 전부 적용한다 (가장 좁고 조용한 풀)."""
        return {
            GLOBAL_TIER: self.tier_a,
            NEGATIVE_TIER: self.tier_b,
            CRISIS_TIER: self.tier_c,
        }

    @property
    def all_blocklist_terms(self) -> tuple[str, ...]:
        return self.tier_a + self.tier_b + self.tier_c

    # --- 검색어 로테이션 ----------------------------------------------------
    def rotated_queries(self, sub: Subcategory, day_of_year: int) -> list[str]:
        """하루치 검색어를 고른다 (4개 중 3개).

        skip 인덱스에 세분류 index를 더하는 이유:
        전 세분류가 같은 날 같은 위치의 쿼리를 동시에 빠뜨리면
        그날 확보되는 영상 풀의 성격이 한쪽으로 쏠린다.
        (예: 모든 카테고리에서 '명상' 계열 쿼리만 빠지는 날)
        """
        queries = list(sub.search_queries)
        if len(queries) <= MAX_QUERIES_PER_SUBCATEGORY:
            return queries

        # skip 다음 위치부터 순환하며 고른다.
        #
        # 이전 구현은 skip 하나를 빼고 남은 목록의 앞에서 3개를 잘랐다(kept[:3]).
        # 검색어가 4개일 때는 모든 항목이 돌아가며 뽑혔지만, 5개가 되는 순간
        # 마지막 항목이 단 하루도 선택되지 않는다 — 남은 4개 중 앞 3개만 쓰므로
        # 5번째는 skip이 아닐 때 항상 4번째 자리에 있다가 잘려 나간다.
        # 조용히 죽은 검색어는 로그에도 안 남아서 알아채기 어렵다.
        skip = (day_of_year + sub.index) % len(queries)
        rotated = queries[skip + 1 :] + queries[:skip]
        return rotated[:MAX_QUERIES_PER_SUBCATEGORY]

    def total_search_calls(self, day_of_year: int) -> int:
        return sum(len(self.rotated_queries(s, day_of_year)) for s in self.subcategories)

    # --- 위기 카테고리 ------------------------------------------------------
    @property
    def crisis_queries(self) -> tuple[str, ...]:
        return tuple(self.crisis["search_queries"])

    @property
    def forbidden_query_patterns(self) -> tuple[str, ...]:
        return tuple(self.crisis["forbidden_query_patterns"])

    @property
    def crisis_max_per_channel(self) -> int:
        """위기 카테고리에서 한 채널이 차지할 수 있는 최대 건수.

        일반 카테고리에는 적용하지 않는다 — 위기 풀만 화이트리스트 우선 정렬 탓에
        상위 채널이 슬롯을 독식하는 구조라서 생긴 규칙이다.
        """
        raw = self.crisis.get("max_per_channel", CRISIS_MAX_PER_CHANNEL)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise TaxonomyError(
                f"crisis_response.content_policy.max_per_channel이 정수가 아니다: {raw!r}"
            ) from None
        if value < 1:
            raise TaxonomyError(
                f"crisis_response.content_policy.max_per_channel은 1 이상이어야 한다: {value}"
            )
        return value

    @property
    def crisis_per_channel_ladder(self) -> tuple[int, ...]:
        """확보량이 상한에 막힐 때 순차 완화할 값들 (기본 3 → 4 → 5)."""
        base = self.crisis_max_per_channel
        return tuple(base + step for step in range(CRISIS_PER_CHANNEL_STEPS))


def load_taxonomy(path: Path) -> Taxonomy:
    with path.open(encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)
    if not isinstance(raw, dict):
        raise TaxonomyError(f"{path}: 최상위가 매핑이 아니다")
    return Taxonomy(raw)


# --- 파싱 보조 ---------------------------------------------------------------


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise TaxonomyError(f"taxonomy.yaml에 '{key}'가 없다")
    return mapping[key]


def _tier_terms(tiers: dict[str, Any], name: str) -> tuple[str, ...]:
    tier = _require(tiers, name)
    terms = tier.get("terms")
    if not terms:
        raise TaxonomyError(f"blocklist_tiers.{name}.terms가 비어 있다")
    return tuple(str(t) for t in terms)


def _parse_negative_parents(raw: dict[str, Any], tiers: dict[str, Any]) -> frozenset[str]:
    """tier_b의 적용 대상 대분류를 applies_to 문장에서 추출한다.

    applies_to는 산문이지만 대분류 id를 그대로 담고 있어, 실제 categories의
    id와 대조해 뽑는다. 하나도 못 찾으면 조용히 넘기지 않고 실패시킨다
    (필터가 통째로 빠진 채 배포되는 게 최악이다).
    """
    applies_to = str(_require(tiers[NEGATIVE_TIER], "applies_to"))
    parents = frozenset(
        str(c["id"]) for c in raw.get("categories", []) if str(c["id"]) in applies_to
    )
    if not parents:
        raise TaxonomyError(
            f"blocklist_tiers.{NEGATIVE_TIER}.applies_to에서 대분류 id를 찾지 못했다: "
            f"{applies_to!r}"
        )
    return parents


def _parse_subcategories(raw: dict[str, Any]) -> tuple[Subcategory, ...]:
    subs: list[Subcategory] = []
    index = 0
    for category in _require(raw, "categories"):
        parent = str(category["id"])
        for sub in category.get("subcategories", []):
            queries = sub.get("search_queries")
            if not queries:
                raise TaxonomyError(f"{sub.get('id')}: search_queries가 비어 있다")
            subs.append(
                Subcategory(
                    id=str(sub["id"]),
                    parent=parent,
                    label=str(sub["label"]),
                    tone=str(sub.get("tone", "")),
                    search_queries=tuple(str(q) for q in queries),
                    index=index,
                )
            )
            index += 1
    if not subs:
        raise TaxonomyError("세분류가 하나도 없다")
    if len(subs) != EXPECTED_SUBCATEGORIES:
        # 치명적이지는 않지만 쿼터 예산이 세분류 수에 직결되므로 눈에 띄게 남긴다.
        raise TaxonomyError(
            f"세분류가 {len(subs)}개다. PLAN.md 확정치는 {EXPECTED_SUBCATEGORIES}개이며, "
            "개수가 바뀌면 쿼터 예산을 다시 산정해야 한다."
        )
    return tuple(subs)


def _parse_crisis(raw: dict[str, Any]) -> dict[str, Any]:
    safety = _require(raw, "safety")
    response = _require(safety, "crisis_response")
    policy = _require(response, "content_policy")
    for key in ("search_queries", "forbidden_query_patterns"):
        if not policy.get(key):
            raise TaxonomyError(f"crisis_response.content_policy.{key}가 비어 있다")
    return policy
