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


class ResearchGraphState(TypedDict):
    prompt: str
    collection: str
    agent_id: str
    thread_id: str | None
    user_id: str
    collected_vars: dict
    response: NotRequired[dict[str, Any]]


class ResearchAgentGraph:
    def __init__(self, rag_query_service: RagRunner) -> None:
        self._rag_query_service = rag_query_service
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
        graph.add_node("run_existing_rag_flow", self._run_existing_flow)
        graph.set_entry_point("run_existing_rag_flow")
        graph.add_edge("run_existing_rag_flow", END)
        return graph.compile()

    def _run_existing_flow(self, state: ResearchGraphState) -> ResearchGraphState:
        response = self._rag_query_service.run(
            prompt=state["prompt"],
            collection=state["collection"],
            agent_id=state["agent_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            collected_vars=state["collected_vars"],
        )
        return {**state, "response": response}
