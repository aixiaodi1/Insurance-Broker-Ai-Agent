from datetime import UTC, datetime
from typing import Any, NotRequired, Protocol, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - dependency is declared for normal runtime.
    END = "__end__"
    StateGraph = None


class RagRunner(Protocol):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict: ...


class EvidenceRegistry(Protocol):
    def query(self, prompt: str) -> dict[str, Any]: ...


class ResearchGraphState(TypedDict):
    prompt: str
    collection: str
    agent_id: str
    thread_id: str | None
    user_id: str
    collected_vars: dict
    evidence_registry_result: NotRequired[dict[str, Any]]
    response: NotRequired[dict[str, Any]]


class ResearchAgentGraph:
    def __init__(
        self,
        rag_query_service: RagRunner,
        evidence_source_registry: EvidenceRegistry | None = None,
    ) -> None:
        self._rag_query_service = rag_query_service
        self._evidence_source_registry = evidence_source_registry
        self._graph = self._build_graph()

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        state: ResearchGraphState = {
            "prompt": prompt,
            "collection": collection,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "collected_vars": collected_vars or {},
        }
        result = self._graph.invoke(state) if self._graph is not None else self._run_existing_flow(state)
        return result["response"]

    def _build_graph(self):
        if StateGraph is None:
            return None
        graph = StateGraph(ResearchGraphState)
        graph.add_node("load_evidence_sources", self._load_evidence_sources)
        graph.add_node("run_existing_rag_flow", self._run_existing_flow)
        graph.set_entry_point("load_evidence_sources")
        graph.add_edge("load_evidence_sources", "run_existing_rag_flow")
        graph.add_edge("run_existing_rag_flow", END)
        return graph.compile()

    def _load_evidence_sources(self, state: ResearchGraphState) -> ResearchGraphState:
        if self._evidence_source_registry is None:
            return state
        evidence = self._evidence_source_registry.query(state["prompt"])
        return {**state, "evidence_registry_result": evidence}

    def _run_existing_flow(self, state: ResearchGraphState) -> ResearchGraphState:
        response = self._rag_query_service.run(
            prompt=state["prompt"],
            collection=state["collection"],
            agent_id=state["agent_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            collected_vars=state["collected_vars"],
        )
        if state.get("evidence_registry_result"):
            response = _decorate_response_with_evidence_registry(
                response,
                state["evidence_registry_result"],
            )
        return {**state, "response": response}


def _decorate_response_with_evidence_registry(
    response: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    timestamp = response.get("startedAt") or datetime.now(UTC).isoformat()
    run_id = str(response.get("id") or "run")
    node_id = "load_evidence_sources"
    company_count = len(evidence.get("companyMatches") or [])
    material_count = len(evidence.get("materialMatches") or [])
    detail = evidence.get("summary") or (
        f"Matched {company_count} company source entries and {material_count} official material candidates."
    )
    node = {
        "id": node_id,
        "label": "Load evidence sources",
        "status": "succeeded",
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "durationMs": 0,
        "stateSummary": detail,
    }
    event = {
        "id": f"{run_id}_evt_{node_id}",
        "nodeId": node_id,
        "type": "tool_call",
        "timestamp": timestamp,
        "title": "Load evidence sources",
        "detail": detail,
        "payload": evidence,
    }
    tool_call = {
        "id": f"{run_id}_tool_source_registry_lookup",
        "nodeId": node_id,
        "name": "source_registry_lookup",
        "status": "succeeded",
        "arguments": {"prompt": response.get("prompt", "")},
        "durationMs": 0,
        "resultPreview": detail,
    }
    response_json = {
        **(response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}),
        "evidenceSourceRegistry": evidence,
    }
    return {
        **response,
        "nodes": [node, *(response.get("nodes") or [])],
        "events": [event, *(response.get("events") or [])],
        "toolCalls": [tool_call, *(response.get("toolCalls") or [])],
        "responseJson": response_json,
    }
