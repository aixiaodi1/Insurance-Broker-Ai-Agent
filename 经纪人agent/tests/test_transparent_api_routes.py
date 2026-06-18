import json

from fastapi.testclient import TestClient

from app.main import app


class FakeLLM:
    def generate(self, prompt: str, system_prompt: str | None = None, tools: list[dict] | None = None, tool_choice: str | dict | None = None) -> dict:
        return {
            "answer": json.dumps(
                {
                    "intent_anchor": {
                        "user_goal": "See the process",
                        "real_blocker": "The agent flow is opaque",
                        "scope_direction": "inspect",
                        "constraints": [],
                        "needs_execution": False,
                        "confidence": 0.9,
                    },
                    "task_decomposition": {
                        "knowledge_gaps": ["runtime shape"],
                        "hypotheses": [{"id": "H1", "claim": "streaming is visible", "falsifiable_by": "no stream events"}],
                        "verification_paths": [{"hypothesis_id": "H1", "path": "/agent/research/stream"}],
                        "dependency_graph": ["H1"],
                        "ordered_tasks": [{"id": "T1", "description": "show process", "depends_on": [], "status": "pending"}],
                    },
                    "execution_mode": "plan_only",
                    "next_action": "show plan",
                },
                ensure_ascii=False,
            )
        }


def test_research_stream_route_returns_transparent_process_events(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: FakeLLM())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/agent/research/stream",
        json={"user_id": "user-1", "thread_id": "thread-1", "message": "plan only: show process"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert [event["type"] for event in events] == [
        "run_started",
        "goal_anchored",
        "plan_updated",
        "final_answer",
        "run_finished",
    ]
    assert events[1]["goal"]["goal"] == "See the process"


def test_research_stream_route_reports_missing_llm_configuration(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "build_memory_extractor_from_settings", lambda settings: None)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/agent/research/stream",
        json={"user_id": "user-1", "message": "show process"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert events[0]["type"] == "error"
    assert "LLM" in events[0]["summary"]
