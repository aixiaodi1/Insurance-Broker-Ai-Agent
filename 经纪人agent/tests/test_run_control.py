from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.run_control import RunControlStore
from app.main import app


def test_run_control_store_persists_interrupt_and_editable_guidance(tmp_path: Path):
    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    store.start_run("run-1", thread_id="thread-1", user_id="user-1", state={"goal": "inspect repo"})

    queued = store.upsert_guidance("run-1", "先看 README", priority="normal")
    edited = store.upsert_guidance("run-1", "重点看 Agent loop", priority="immediate")
    store.request_interrupt("run-1")

    assert edited["id"] == queued["id"]
    assert store.get_pending_guidance("run-1")["content"] == "重点看 Agent loop"
    assert store.get_pending_guidance("run-1")["priority"] == "immediate"
    assert store.interrupt_requested("run-1") is True

    store.mark_guidance_applied("run-1")
    store.finish_run("run-1", status="interrupted", state={"goal": "inspect repo", "observations": ["README"]})

    assert store.get_pending_guidance("run-1") is None
    assert store.get_run("run-1")["status"] == "interrupted"
    assert store.get_run("run-1")["state"]["observations"] == ["README"]


def test_run_control_routes_update_the_shared_store(monkeypatch, tmp_path: Path):
    import app.api.routes as routes

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    store.start_run("run-api", thread_id="thread-1", user_id="user-1", state={})
    monkeypatch.setattr(routes, "_run_control_store", lambda: store)
    client = TestClient(app)

    guidance = client.put(
        "/agent/runs/run-api/guidance",
        json={"content": "改为分析 ReAct", "priority": "immediate"},
    )
    interrupted = client.post("/agent/runs/run-api/control", json={"action": "interrupt"})
    deleted = client.delete("/agent/runs/run-api/guidance")

    assert guidance.status_code == 200
    assert guidance.json()["guidance"]["content"] == "改为分析 ReAct"
    assert interrupted.status_code == 200
    assert store.interrupt_requested("run-api") is True
    assert deleted.status_code == 200
    assert store.get_pending_guidance("run-api") is None


def test_run_control_routes_return_404_for_unknown_run(monkeypatch, tmp_path: Path):
    import app.api.routes as routes

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    monkeypatch.setattr(routes, "_run_control_store", lambda: store)
    client = TestClient(app)

    response = client.post("/agent/runs/missing/control", json={"action": "interrupt"})

    assert response.status_code == 404
