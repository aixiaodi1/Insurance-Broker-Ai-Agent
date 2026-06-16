from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep, DownloadedFile
from app.web_acquisition.storage import SQLiteAcquisitionStore


class FakeWebAcquisitionService:
    def __init__(self, store: SQLiteAcquisitionStore) -> None:
        self.store = store
        self.store.init_schema()

    async def acquire(
        self,
        url: str,
        goal: str,
        allowed_domains: list[str] | None = None,
        strategy: str = "auto",
        max_steps: int = 20,
        timeout_seconds: int = 90,
    ) -> dict:
        task_id = self.store.create_task(url, goal, allowed_domains, strategy)
        result = AcquisitionResult(
            success=True,
            input_url=url,
            final_url=url,
            strategy_used="http",
            title="API Product",
            steps=[AcquisitionStep(layer="http", action="fetch", description="Fetched via fake service")],
            downloaded_files=[
                DownloadedFile(
                    source_url=f"{url}/clause.pdf",
                    final_url=f"{url}/clause.pdf",
                    file_path="data/downloads/clause.pdf",
                    filename="clause.pdf",
                    content_type="application/pdf",
                    size_bytes=12,
                    sha256="abc123",
                )
            ],
        )
        self.store.finish_task(task_id, "succeeded", result)
        return {"task_id": task_id, "status": "succeeded", "result": result}


def test_web_acquisition_run_route_persists_and_returns_task(tmp_path, monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "web_acquisition_db_path", tmp_path / "acquisition.sqlite3")
    monkeypatch.setattr(routes, "build_web_acquisition_service", lambda: FakeWebAcquisitionService(SQLiteAcquisitionStore(settings.web_acquisition_db_path)))

    client = TestClient(app)
    response = client.post(
        "/web-acquisition/run",
        json={
            "url": "https://www.example.com/product",
            "goal": "查找公开保险资料",
            "allowed_domains": ["example.com"],
            "strategy": "auto",
            "max_steps": 5,
            "timeout_seconds": 30,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["result"]["strategy_used"] == "http"
    assert body["result"]["title"] == "API Product"
    assert body["task_id"]

    task_response = client.get(f"/web-acquisition/tasks/{body['task_id']}")
    assert task_response.status_code == 200
    assert task_response.json()["result"]["title"] == "API Product"


def test_web_acquisition_steps_and_files_routes_return_persisted_views(tmp_path, monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "web_acquisition_db_path", tmp_path / "acquisition.sqlite3")
    monkeypatch.setattr(routes, "build_web_acquisition_service", lambda: FakeWebAcquisitionService(SQLiteAcquisitionStore(settings.web_acquisition_db_path)))

    client = TestClient(app)
    run = client.post(
        "/web-acquisition/run",
        json={"url": "https://www.example.com/product", "goal": "查找公开保险资料"},
    ).json()

    steps = client.get(f"/web-acquisition/tasks/{run['task_id']}/steps")
    files = client.get(f"/web-acquisition/tasks/{run['task_id']}/files")

    assert steps.status_code == 200
    assert steps.json()["steps"][0]["description"] == "Fetched via fake service"
    assert files.status_code == 200
    assert files.json()["files"][0]["sha256"] == "abc123"


def test_web_acquisition_task_route_returns_404_for_missing_task(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "web_acquisition_db_path", tmp_path / "acquisition.sqlite3")

    client = TestClient(app)
    response = client.get("/web-acquisition/tasks/missing")

    assert response.status_code == 404
