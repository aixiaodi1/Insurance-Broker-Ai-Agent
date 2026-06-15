from typing import Any, TypedDict
from uuid import uuid4


class AgentState(TypedDict, total=False):
    run_id: str
    session_id: str
    thread_id: str
    user_id: str
    user_input: str
    task_type: str
    route_reason: str | None
    requested_command: str | None
    thread_id_provided: bool
    user_level: str
    company_name: str | None
    product_name: str | None
    aliases: list[str]
    local_candidates: list[dict[str, Any]]
    web_leads: list[dict[str, Any]]
    official_sources: list[dict[str, Any]]
    pdf_assets: list[dict[str, Any]]
    product_identity: dict[str, Any] | None
    iachina_status: dict[str, Any] | None
    rag_citations: list[dict[str, Any]]
    source_observations: list[dict[str, Any]]
    evidence_score: dict[str, Any] | None
    stop_reasons: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    conversation_summary: str | None
    tool_events: list[dict[str, Any]]
    user_visible_steps: list[dict[str, Any]]
    context_budget: dict[str, Any]
    memory_snapshot: str | None
    remembered_context: dict[str, Any]
    memory_citations: list[dict[str, Any]]
    final_summary: str | None
    final_report: str | None


def new_agent_state(user_id: str, user_input: str, thread_id: str) -> AgentState:
    return {
        "run_id": str(uuid4()),
        "session_id": "",
        "thread_id": thread_id,
        "user_id": user_id,
        "user_input": user_input,
        "task_type": "unknown",
        "route_reason": None,
        "requested_command": None,
        "thread_id_provided": True,
        "user_level": "novice",
        "company_name": None,
        "product_name": None,
        "aliases": [],
        "local_candidates": [],
        "web_leads": [],
        "official_sources": [],
        "pdf_assets": [],
        "product_identity": None,
        "iachina_status": None,
        "rag_citations": [],
        "source_observations": [],
        "evidence_score": None,
        "stop_reasons": [],
        "messages": [{"role": "user", "content": user_input}],
        "conversation_summary": None,
        "tool_events": [],
        "user_visible_steps": [],
        "context_budget": {},
        "memory_snapshot": None,
        "remembered_context": {},
        "memory_citations": [],
        "final_summary": None,
        "final_report": None,
    }
