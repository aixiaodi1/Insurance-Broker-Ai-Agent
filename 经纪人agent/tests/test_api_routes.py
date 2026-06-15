import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


class FakeLLM:
    def __init__(self, execution_mode: str = "plan_only") -> None:
        self.execution_mode = execution_mode
        self.calls: list[dict] = []

    def generate(self, prompt: str, system_prompt: str | None = None, tools: list[dict] | None = None, tool_choice: str | dict | None = None) -> dict:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "tools": tools, "tool_choice": tool_choice})
        return {
            "answer": json.dumps(
                {
                    "intent_anchor": {
                        "user_goal": "Understand the user request transparently",
                        "real_blocker": "The old route hid intent and task decomposition",
                        "scope_direction": "inspect and plan",
                        "constraints": ["do not force insurance evidence workflow"],
                        "needs_execution": self.execution_mode == "execute",
                        "confidence": 0.9,
                    },
                    "task_decomposition": {
                        "knowledge_gaps": ["runtime context", "available tools"],
                        "hypotheses": [{"id": "H1", "claim": "transparent planning is visible", "falsifiable_by": "missing trace events"}],
                        "verification_paths": [{"hypothesis_id": "H1", "path": "/agent/research"}],
                        "dependency_graph": ["H1"],
                        "ordered_tasks": [{"id": "T1", "description": "show public planning", "depends_on": [], "status": "pending"}],
                    },
                    "execution_mode": self.execution_mode,
                    "next_action": "show public planning",
                },
                ensure_ascii=False,
            )
        }


def test_health_route_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_research_route_module_does_not_import_legacy_research_runtime():
    routes_path = Path(__file__).resolve().parents[1] / "app" / "api" / "routes.py"
    routes_source = routes_path.read_text(encoding="utf-8")

    assert "from app.agents.runtime import run_research_task" not in routes_source
    assert "run_research_task(" not in routes_source


def test_research_route_uses_transparent_mainline(tmp_path, monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "agent_memory.sqlite3")
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path)
    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: FakeLLM())

    client = TestClient(app)
    response = client.post(
        "/agent/research",
        json={"user_id": "user-1", "thread_id": "thread-1", "message": "show me the process"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    assert body["task_type"] == "transparent_react"
    assert body["evidence_score"] is None
    assert "我先不执行工具" in body["final_summary"]
    trace_types = [event["type"] for event in body["workflow_trace"]]
    assert "context_loaded" in trace_types
    assert "intent_anchor" in trace_types
    assert "task_decomposition" in trace_types
    assert "novice_intake" not in trace_types
    assert "rag_citation_check" not in trace_types


def test_research_route_reports_missing_llm_without_template_answer(tmp_path, monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "agent_memory.sqlite3")
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path)
    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: None)

    client = TestClient(app)
    response = client.post("/agent/research", json={"user_id": "user-1", "message": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["task_type"] == "transparent_react"
    assert body["final_summary"] == "LLM is not configured; transparent ReAct runtime cannot start."
    assert body["stop_reasons"][0]["code"] == "llm_not_configured"


def test_research_route_persists_raw_user_message_under_transparent_mainline(tmp_path, monkeypatch):
    from app.config import settings
    from app.memory.sqlite_memory import SQLiteMemory
    import app.api.routes as routes

    db_path = tmp_path / "agent_memory.sqlite3"
    monkeypatch.setattr(settings, "memory_db_path", db_path)
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path)
    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: FakeLLM())

    client = TestClient(app)
    client.post(
        "/agent/research",
        json={"user_id": "user-1", "thread_id": "thread-memory", "message": "remember marker one"},
    )

    memory = SQLiteMemory(db_path)
    results = memory.search_messages("remember marker one")
    assert results


def test_memory_search_route_returns_matches(tmp_path, monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "agent_memory.sqlite3")
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "hermes_memory_dir", tmp_path)
    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: FakeLLM())

    client = TestClient(app)
    client.post("/agent/research", json={"user_id": "user-1", "message": "alpha transparent memory"})
    response = client.get("/agent/memory/search", params={"q": "alpha transparent"})
    assert response.status_code == 200
    assert response.json()["results"][0]["content"] == "alpha transparent memory"


def test_research_stream_route_returns_transparent_process_events(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: FakeLLM())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/agent/research/stream",
        json={"user_id": "user-1", "thread_id": "thread-1", "message": "show process"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert [event["type"] for event in events] == [
        "run_started",
        "context_loaded",
        "intent_anchor",
        "task_decomposition",
        "final_answer",
        "run_finished",
    ]
    assert events[2]["intent"]["real_blocker"] == "The old route hid intent and task decomposition"
