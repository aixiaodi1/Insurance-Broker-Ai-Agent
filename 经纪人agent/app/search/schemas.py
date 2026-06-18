from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


NetworkRequirement = Literal["required", "conditional", "not_needed"]
Freshness = Literal["not_required", "latest", "recent", "as_of"]
RiskLevel = Literal["low", "medium", "high"]
QueryRole = Literal["official", "document", "regulatory", "freshness"]


@dataclass(slots=True, frozen=True)
class SearchRequest:
    original_question: str
    query_goal: str = ""
    limit: int = 8


@dataclass(slots=True, frozen=True)
class PlannedQuery:
    role: QueryRole
    text: str
    model_suggested_terms: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class SearchPlan:
    original_question: str
    normalized_question: str
    network_requirement: NetworkRequirement
    freshness: Freshness
    source_preference: tuple[str, ...]
    document_types: tuple[str, ...]
    risk_level: RiskLevel
    protected_entities: tuple[str, ...]
    queries: tuple[PlannedQuery, ...]


@dataclass(slots=True)
class SearchItem:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    rank: int = 0
    score: float = 0.0
    published_at: str | None = None
    trust_tier: str = "unknown"
    risk_flags: list[str] = field(default_factory=list)
    original_url: str = ""
    normalized_url: str = ""
    query_roles: list[str] = field(default_factory=list)
    rrf_score: float = 0.0
    rule_adjustment: float = 0.0
    source_type: str = "unknown"


@dataclass(slots=True)
class SearchProviderResult:
    provider: str
    ok: bool
    results: list[SearchItem] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class SearchResponse:
    query: str
    provider_used: str
    fallback_used: bool
    results: list[SearchItem]
    errors: list[dict] = field(default_factory=list)
    content_kind: str = "search_results"
    plan: SearchPlan | None = None
    degradation: str = "none"
    provider_statuses: list[dict] = field(default_factory=list)
    public_trace: list[dict] = field(default_factory=list)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        ...
