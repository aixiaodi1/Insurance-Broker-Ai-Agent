from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.agents.graphs.research_graph import build_research_graph, run_research_graph
from app.agents.nodes.memory_nodes import load_thread_memory
from app.agents.state import new_agent_state
from app.memory.sqlite_memory import SQLiteMemory


def test_build_research_graph_uses_langgraph_checkpointer_and_store():
    checkpointer = InMemorySaver()
    store = InMemoryStore()
    graph = build_research_graph(
        checkpointer=checkpointer,
        store=store,
    )
    config = {"configurable": {"thread_id": "user-1:task-store"}}
    state = new_agent_state("user-1", "alpha", "user-1:task-store")

    graph.invoke(state, config=config)

    assert callable(getattr(graph, "invoke", None))
    assert checkpointer.get_tuple(config) is not None
    assert store.get(("thread", "user-1:task-store"), "summary") is not None


def test_research_graph_runs_memory_nodes(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    first_session_id = memory.create_session("user-1", "user-1:task-1", "alpha", "research")
    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="user-1:task-1",
        summary="Previous alpha research summary",
        latest_session_id=first_session_id,
        final_summary="Previous answer",
    )

    state = new_agent_state("user-1", "alpha follow up", "user-1:task-1")
    result = run_research_graph(state, memory=memory)

    assert result["remembered_context"]["thread_summary"]["summary"] == "Previous alpha research summary"
    assert any(item["source"] == "thread_summary" for item in result["memory_citations"])
    assert memory.get_thread_summary("user-1:task-1")["latest_session_id"] == result["session_id"]


def test_load_thread_memory_adds_summary_and_recent_messages_to_state(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:task-1", "alpha", "research")
    memory.add_message(session_id, "user", "previous alpha question")
    memory.add_message(session_id, "assistant", "previous alpha answer")
    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="user-1:task-1",
        summary="Previous thread summary",
        latest_session_id=session_id,
        final_summary="previous alpha answer",
    )
    state = new_agent_state("user-1", "new alpha question", "user-1:task-1")

    result = load_thread_memory(state, memory)

    assert "Previous thread summary" in result["conversation_summary"]
    assert [message["content"] for message in result["messages"][:2]] == [
        "previous alpha question",
        "previous alpha answer",
    ]


def test_research_graph_compacts_loaded_thread_messages(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:task-1", "alpha", "research")
    for index in range(20):
        memory.add_message(session_id, "user", f"previous message {index}")
    state = new_agent_state("user-1", "new alpha question", "user-1:task-1")
    state["context_budget"] = {"max_messages": 4, "max_tool_events": 20}

    result = run_research_graph(state, memory=memory)

    assert len(result["messages"]) == 4
    assert "previous message" in result["conversation_summary"]


def test_evidence_memory_is_recalled_as_clue_not_scored_as_formal_evidence(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:task-1", "alpha", "research")
    memory.upsert_evidence_memory(
        product_name="Alpha Product",
        title="Remembered alpha PDF",
        source_url="https://example.com/alpha.pdf",
        source_tier="S1",
        chunk_id="alpha-001",
        file_hash="hash-alpha",
        source_session_id=session_id,
    )
    state = new_agent_state("user-1", "alpha", "user-1:task-1")

    result = run_research_graph(state, memory=memory)

    assert result["remembered_context"]["evidence_memories"]
    assert result["evidence_score"]["official_evidence"] == 0
    assert result["evidence_score"]["total"] < 60
