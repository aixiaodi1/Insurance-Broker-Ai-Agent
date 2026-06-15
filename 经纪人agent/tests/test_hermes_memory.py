from fastapi.testclient import TestClient

from app.main import app
from app.memory.hermes import HermesMemoryStore
from app.memory.sqlite_memory import SQLiteMemory


def test_hermes_memory_store_add_replace_remove_and_snapshot(tmp_path):
    store = HermesMemoryStore(tmp_path / "memories", memory_char_limit=120, user_char_limit=80)

    first = store.add("memory", "Project note one")
    second = store.add("memory", "Project note two")
    user_note = store.add("user", "Prefers concise responses")

    assert first["success"] is True
    assert second["success"] is True
    assert user_note["success"] is True
    assert "MEMORY" in store.render_snapshot()
    assert "USER" in store.render_snapshot()
    assert "§" in (tmp_path / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    replaced = store.replace("memory", "Project note one", "Project note one updated")
    removed = store.remove("memory", "Project note two")

    assert replaced["success"] is True
    assert removed["success"] is True
    assert "Project note one updated" in (tmp_path / "memories" / "MEMORY.md").read_text(encoding="utf-8")


def test_hermes_memory_store_blocks_unsafe_content_and_limit(tmp_path):
    store = HermesMemoryStore(tmp_path / "memories", memory_char_limit=20, user_char_limit=20)

    blocked = store.add("user", "api key: secret-token")
    too_large = store.add("memory", "abcdefghijklmnopqrstuvwxyz")

    assert blocked["success"] is False
    assert too_large["success"] is False


def test_sqlite_memory_supports_search_and_session_browse(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()

    session_a = memory.create_session("user-1", "user-1:thread-a", "Thread A", "research")
    session_b = memory.create_session("user-1", "user-1:thread-b", "Thread B", "research")

    memory.add_message(session_id=session_a, role="user", content="alpha product details")
    memory.add_message(session_id=session_a, role="assistant", content="alpha summary")
    memory.add_message(session_id=session_b, role="user", content="beta product details")

    search_results = memory.search_messages("alpha")
    sessions = memory.list_sessions(user_id="user-1", limit=10)
    session_messages = memory.get_session_messages(session_a, limit=10)

    assert any(item["content"] == "alpha summary" for item in search_results)
    assert any(item["role"] == "assistant" for item in search_results)
    assert sessions[0]["thread_id"] in {"user-1:thread-a", "user-1:thread-b"}
    assert [item["content"] for item in session_messages] == ["alpha product details", "alpha summary"]


def test_sqlite_memory_supports_structured_memory_layers(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:thread-a", "Thread A", "research")

    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="user-1:thread-a",
        summary="Looked up alpha product official evidence.",
        latest_session_id=session_id,
        final_summary="Alpha summary",
    )
    memory.upsert_memory_fact(
        namespace="user:user-1:profile",
        key="preferred_output_style",
        value={"style": "concise"},
        source_session_id=session_id,
        confidence=0.9,
    )
    memory.upsert_project_memory(
        kind="product_alias",
        key="alpha",
        value={"canonical": "Alpha Product"},
        source_session_id=session_id,
    )
    memory.upsert_evidence_memory(
        product_name="Alpha Product",
        title="Alpha official PDF",
        source_url="https://example.com/alpha.pdf",
        source_tier="S1",
        chunk_id="alpha-001",
        file_hash="hash-alpha",
        source_session_id=session_id,
    )

    remembered = memory.recall_memory(
        user_id="user-1",
        thread_id="user-1:thread-a",
        query="alpha",
    )

    assert remembered["thread_summary"]["summary"] == "Looked up alpha product official evidence."
    assert remembered["facts"][0]["key"] == "preferred_output_style"
    assert remembered["project_memories"][0]["kind"] == "product_alias"
    assert remembered["evidence_memories"][0]["chunk_id"] == "alpha-001"
    assert {item["source"] for item in remembered["citations"]} == {
        "thread_summary",
        "memory_fact",
        "project_memory",
        "evidence_memory",
    }


def test_memory_api_can_manage_and_snapshot(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path / "hermes_memories")
    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "memory.sqlite3")

    client = TestClient(app)
    response = client.post(
        "/agent/memory",
        json={
            "target": "user",
            "action": "add",
            "content": "Prefer concise answers",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["success"] is True

    snapshot = client.get("/agent/memory/snapshot")
    assert snapshot.status_code == 200
    assert "USER" in snapshot.json()["snapshot"]


def test_transparent_research_does_not_invent_structured_user_facts(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path / "hermes_memories")
    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "memory.sqlite3")
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")

    client = TestClient(app)
    client.post(
        "/agent/research",
        json={"user_id": "user-1", "message": "alpha product official evidence"},
    )

    response = client.get("/agent/memory/facts", params={"user_id": "user-1"})

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_memory_management_api_covers_structured_layers_and_export(tmp_path, monkeypatch):
    from app.audit.logger import AuditLogger
    from app.config import settings

    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path / "hermes_memories")
    monkeypatch.setattr(settings, "memory_db_path", db_path)
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")

    memory = SQLiteMemory(db_path)
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:thread-a", "alpha", "research")
    memory.add_message(session_id=session_id, role="user", content="alpha request")
    fact_id = memory.upsert_memory_fact(
        namespace="user:user-1:profile",
        key="preferred_output_style",
        value={"style": "table"},
        source_session_id=session_id,
    )
    memory.upsert_project_memory("product_alias", "alpha", {"canonical": "Alpha Product"}, session_id)
    memory.upsert_evidence_memory(
        product_name="Alpha Product",
        title="Alpha official PDF",
        source_url="https://example.com/alpha.pdf",
        source_tier="S1",
        chunk_id="alpha-001",
        file_hash="hash-alpha",
        source_session_id=session_id,
    )
    AuditLogger(memory=memory, runs_dir=tmp_path / "runs").log_tool_event(
        run_id="run-1",
        thread_id="user-1:thread-a",
        node="official_source_verify",
        tool="http_get",
        status="success",
        input_json={"url": "https://example.com/alpha.pdf"},
        output_json={"status_code": 200},
        url="https://example.com/alpha.pdf",
    )

    client = TestClient(app)
    project = client.get("/agent/memory/project", params={"q": "alpha"})
    evidence = client.get("/agent/memory/evidence", params={"q": "alpha"})
    events = client.get("/agent/memory/tool-events", params={"q": "alpha"})
    exported = client.get("/agent/memory/export", params={"session_id": session_id})
    deleted = client.delete(f"/agent/memory/facts/{fact_id}")
    facts = client.get("/agent/memory/facts", params={"user_id": "user-1"})

    assert project.status_code == 200
    assert project.json()["results"][0]["key"] == "alpha"
    assert evidence.status_code == 200
    assert evidence.json()["results"][0]["chunk_id"] == "alpha-001"
    assert events.status_code == 200
    assert events.json()["results"][0]["tool"] == "http_get"
    assert exported.status_code == 200
    assert "alpha request" in exported.json()["jsonl"]
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert facts.json()["results"] == []
