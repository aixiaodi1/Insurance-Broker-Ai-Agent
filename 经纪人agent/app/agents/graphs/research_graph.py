from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from app.agents.graphs.evidence_graph import run_evidence_graph
from app.agents.graphs.intake_graph import run_intake_graph
from app.agents.graphs.report_graph import run_report_graph
from app.agents.nodes.context_nodes import compact_context
from app.agents.nodes.memory_nodes import load_thread_memory, save_memory_and_audit
from app.agents.nodes.subagent_node import evidence_search_with_subagent
from app.agents.state import AgentState
from app.config import settings
from app.memory.extraction import MemoryExtractor
from app.memory.sqlite_memory import SQLiteMemory
from app.subagent.factory import build_subagent_runner
from app.subagent.runner import SubagentRunner


def build_research_graph(
    memory: SQLiteMemory | None = None,
    memory_extractor: MemoryExtractor | None = None,
    subagent_runner: SubagentRunner | None = None,
    checkpointer: InMemorySaver | None = None,
    store: InMemoryStore | None = None,
):
    effective_memory = memory or SQLiteMemory(settings.memory_db_path)
    effective_memory.init_schema()
    effective_store = store or InMemoryStore()
    effective_subagent = subagent_runner if subagent_runner is not None else build_subagent_runner()

    graph = StateGraph(AgentState)
    graph.add_node("load_thread_memory", lambda state: load_thread_memory(state, effective_memory))
    graph.add_node(
        "context_compaction",
        lambda state: compact_context(state, llm_client=memory_extractor),
    )
    graph.add_node("intake", run_intake_graph)

    if effective_subagent is not None:
        graph.add_node(
            "evidence_subagent",
            lambda state: evidence_search_with_subagent(state, effective_subagent),
        )
    graph.add_node("evidence", run_evidence_graph)
    graph.add_node("report", run_report_graph)
    graph.add_node(
        "save_memory_and_audit",
        lambda state: _save_memory_node(state, effective_memory, effective_store, memory_extractor),
    )

    graph.add_edge(START, "load_thread_memory")
    graph.add_edge("load_thread_memory", "context_compaction")
    graph.add_edge("context_compaction", "intake")

    if effective_subagent is not None:
        graph.add_conditional_edges(
            "intake",
            _route_evidence,
            {"subagent": "evidence_subagent", "legacy": "evidence"},
        )
        graph.add_edge("evidence_subagent", "report")
        graph.add_edge("evidence", "report")
    else:
        graph.add_edge("intake", "evidence")
        graph.add_edge("evidence", "report")
    graph.add_edge("report", "save_memory_and_audit")
    graph.add_edge("save_memory_and_audit", END)

    return graph.compile(
        checkpointer=checkpointer or InMemorySaver(),
        store=effective_store,
    )


def run_research_graph(
    state: dict,
    memory: SQLiteMemory | None = None,
    memory_extractor: MemoryExtractor | None = None,
    subagent_runner: SubagentRunner | None = None,
) -> dict:
    graph = build_research_graph(
        memory=memory,
        memory_extractor=memory_extractor,
        subagent_runner=subagent_runner,
    )
    return graph.invoke(
        state,
        config={"configurable": {"thread_id": state["thread_id"]}},
    )


def _route_evidence(state: dict) -> str:
    if state.get("product_name"):
        return "subagent"
    return "legacy"


def _save_memory_node(
    state: dict,
    memory: SQLiteMemory,
    store: InMemoryStore,
    memory_extractor: MemoryExtractor | None,
) -> dict:
    state = save_memory_and_audit(state, memory, memory_extractor=memory_extractor)
    store.put(
        ("thread", state["thread_id"]),
        "summary",
        {
            "thread_id": state["thread_id"],
            "user_id": state["user_id"],
            "session_id": state.get("session_id"),
            "final_summary": state.get("final_summary"),
            "evidence_score": state.get("evidence_score"),
        },
    )
    store.put(
        ("user", state["user_id"], "recent_tasks"),
        state["thread_id"],
        {
            "thread_id": state["thread_id"],
            "session_id": state.get("session_id"),
            "task_type": state.get("task_type"),
            "product_name": state.get("product_name"),
        },
    )
    return state
