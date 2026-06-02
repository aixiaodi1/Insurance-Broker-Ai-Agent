from dataclasses import dataclass, field

from app.domain import QueryIntent


@dataclass
class RetrievalLane:
    method: str
    target_content_types: list[str] = field(default_factory=list)
    section_hints: list[str] = field(default_factory=list)
    top_k: int = 10
    weight: float = 1.0
    query: str | None = None


_INTENT_LANES: dict[QueryIntent, list[RetrievalLane]] = {
    QueryIntent.BENEFIT_QUERY: [
        RetrievalLane(method="dense", target_content_types=["insurance_liability", "clause", "exclusion", "disease_definition", "definition", "table_candidate"], weight=1.2),
        RetrievalLane(method="bm25", target_content_types=["insurance_liability", "clause", "exclusion", "disease_definition", "definition"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["2.4", "2.5", "2.6", "10", "11", "13"], weight=1.5, top_k=5),
    ],
    QueryIntent.DISEASE_DEFINITION: [
        RetrievalLane(method="dense", target_content_types=["disease_definition", "definition", "table_candidate"], weight=1.2),
        RetrievalLane(method="bm25", target_content_types=["disease_definition", "definition"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["10", "11", "13"], weight=1.5, top_k=8),
    ],
    QueryIntent.EXCLUSION_QUERY: [
        RetrievalLane(method="dense", target_content_types=["exclusion", "insurance_liability", "disease_definition"], weight=1.2),
        RetrievalLane(method="bm25", target_content_types=["exclusion", "insurance_liability"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["2.6"], weight=1.5, top_k=8),
    ],
    QueryIntent.WAITING_PERIOD: [
        RetrievalLane(method="dense", target_content_types=["waiting_period", "insurance_limitation"], weight=1.0),
        RetrievalLane(method="bm25", target_content_types=["waiting_period", "insurance_liability"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["2.3", "7"], weight=1.5, top_k=5),
    ],
    QueryIntent.AGE_RULE: [
        RetrievalLane(method="dense", target_content_types=["age_rule", "insurance_liability", "clause"], weight=1.0),
        RetrievalLane(method="bm25", target_content_types=["age_rule", "clause"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["1.3", "2.5"], weight=1.5, top_k=5),
    ],
    QueryIntent.CLAIM_MATERIALS: [
        RetrievalLane(method="dense", target_content_types=["claim_material", "clause"], weight=1.0),
        RetrievalLane(method="bm25", target_content_types=["claim_material"], weight=1.0),
        RetrievalLane(method="section_bm25", section_hints=["3.3"], weight=1.5, top_k=5),
    ],
    QueryIntent.COMPARISON_QUERY: [
        RetrievalLane(method="dense", target_content_types=["insurance_liability", "clause"], weight=1.0),
        RetrievalLane(method="bm25", weight=1.0),
    ],
    QueryIntent.SUMMARY_QUERY: [
        RetrievalLane(method="dense", target_content_types=["insurance_liability", "clause"], weight=1.0),
        RetrievalLane(method="bm25", weight=1.0),
    ],
    QueryIntent.GENERAL: [
        RetrievalLane(method="dense", weight=1.0),
        RetrievalLane(method="bm25", weight=1.0),
    ],
}


class RetrievalPlanner:
    def plan(self, intent_type: str, original_query: str, expanded_queries: list[str] | None = None) -> list[RetrievalLane]:
        intent = QueryIntent(intent_type) if intent_type in QueryIntent._value2member_map_ else QueryIntent.GENERAL
        lanes = _INTENT_LANES.get(intent, _INTENT_LANES[QueryIntent.GENERAL])
        return [self._materialize_lane(l, original_query, expanded_queries) for l in lanes]

    def _materialize_lane(self, lane: RetrievalLane, original_query: str, expanded_queries: list[str] | None) -> RetrievalLane:
        if lane.method == "section_bm25" and lane.section_hints:
            section_terms = " ".join(lane.section_hints)
            q = f"{section_terms} {original_query}"
        elif lane.query is not None:
            q = lane.query
        else:
            q = original_query
        return RetrievalLane(
            method=lane.method,
            target_content_types=list(lane.target_content_types),
            section_hints=list(lane.section_hints),
            top_k=lane.top_k,
            weight=lane.weight,
            query=q,
        )

    def describe(self, lanes: list[RetrievalLane]) -> list[dict]:
        return [
            {
                "method": l.method,
                "target_content_types": l.target_content_types,
                "section_hints": l.section_hints,
                "top_k": l.top_k,
                "weight": l.weight,
            }
            for l in lanes
        ]


def filter_by_content_type(matches: list[dict], content_types: list[str]) -> list[dict]:
    if not content_types:
        return matches
    return [
        m for m in matches
        if m.get("metadata", {}).get("content_type") in content_types
    ]


def dedup_matches(matches: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    seen_parent_sections: set[tuple[str, str]] = set()
    result: list[dict] = []
    for m in matches:
        mid = m.get("id", "")
        if mid and mid in seen_ids:
            continue
        seen_ids.add(mid)
        meta = m.get("metadata") or {}
        ps_key = (str(meta.get("parent_id", "")), str(meta.get("section_no", "")))
        if ps_key != ("", ""):
            if ps_key in seen_parent_sections:
                continue
            seen_parent_sections.add(ps_key)
        result.append(m)
    return result
