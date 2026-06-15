from app.agents.nodes.evidence_nodes import (
    evidence_score,
    local_evidence_search,
    product_identity_resolve,
    rag_citation_check,
    web_lead_search,
)


def run_evidence_graph(state: dict) -> dict:
    state = local_evidence_search(state)
    state = web_lead_search(state)
    state = product_identity_resolve(state)
    state = rag_citation_check(state)
    state = evidence_score(state)
    return state
