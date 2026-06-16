# Web Acquisition Stage 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend service orchestration, SQLite persistence, and FastAPI routes for the Web Acquisition Pipeline.

**Architecture:** Keep Stage 4 as a thin integration layer over the existing fetchers. `SQLiteAcquisitionStore` persists tasks/results, `WebAcquisitionService` routes strategies, and `app.api.routes` exposes backend-only endpoints.

**Tech Stack:** Python dataclasses, sqlite3, FastAPI, Pydantic, pytest.

---

### Task 1: SQLite Acquisition Store

**Files:**
- Create: `app/web_acquisition/storage.py`
- Test: `tests/test_web_acquisition_storage.py`

- [ ] **Step 1: Write failing storage tests**

```python
def test_store_persists_task_result_steps_links_and_files(tmp_path):
    store = SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3")
    store.init_schema()
    task_id = store.create_task("https://www.example.com/product", "goal", ["example.com"], "auto")
    result = AcquisitionResult(
        success=True,
        input_url="https://www.example.com/product",
        final_url="https://www.example.com/product",
        strategy_used="http",
        title="Product",
        links=[DiscoveredLink(url="https://www.example.com/product", text="Product", source="http")],
        pdf_links=[DiscoveredLink(url="https://www.example.com/clause.pdf", text="产品条款", source="http")],
        downloaded_files=[DownloadedFile(source_url="https://www.example.com/clause.pdf", final_url="https://www.example.com/clause.pdf", file_path="data/downloads/clause.pdf", filename="clause.pdf", content_type="application/pdf", size_bytes=12, sha256="abc")],
        steps=[AcquisitionStep(layer="http", action="fetch", description="Fetched")],
    )
    store.finish_task(task_id, "succeeded", result)
    task = store.get_task(task_id)
    assert task["status"] == "succeeded"
```

- [ ] **Step 2: Verify tests fail because storage module is missing**

Run: `pytest tests/test_web_acquisition_storage.py -q`

- [ ] **Step 3: Implement `SQLiteAcquisitionStore` with schema, create, finish, get, list steps, list files**

- [ ] **Step 4: Verify storage tests pass**

Run: `pytest tests/test_web_acquisition_storage.py -q`

### Task 2: Web Acquisition Service

**Files:**
- Create: `app/web_acquisition/service.py`
- Modify: `app/web_acquisition/__init__.py`
- Test: `tests/test_web_acquisition_service.py`

- [ ] **Step 1: Write failing service tests**

```python
def test_service_auto_stops_after_successful_http(tmp_path):
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=FakeFetcher(AcquisitionResult(success=True, input_url="https://www.example.com", strategy_used="http")),
        playwright_fetcher=FakeFetcher(AcquisitionResult(success=True, input_url="https://www.example.com", strategy_used="playwright")),
    )
    response = asyncio.run(service.acquire("https://www.example.com", "goal"))
    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "http"
```

- [ ] **Step 2: Verify tests fail because service module is missing**

Run: `pytest tests/test_web_acquisition_service.py -q`

- [ ] **Step 3: Implement service routing for auto and explicit strategies**

- [ ] **Step 4: Verify service tests pass**

Run: `pytest tests/test_web_acquisition_service.py -q`

### Task 3: Backend API Routes

**Files:**
- Modify: `app/config.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_web_acquisition_api_routes.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_web_acquisition_run_route_persists_result(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "web_acquisition_db_path", tmp_path / "acquisition.sqlite3")
    monkeypatch.setattr(routes, "build_web_acquisition_service", lambda: fake_service)
    response = TestClient(app).post("/web-acquisition/run", json={"url": "https://www.example.com", "goal": "goal"})
    assert response.status_code == 200
```

- [ ] **Step 2: Verify tests fail because routes are missing**

Run: `pytest tests/test_web_acquisition_api_routes.py -q`

- [ ] **Step 3: Add request/response models and routes**

- [ ] **Step 4: Verify API tests pass**

Run: `pytest tests/test_web_acquisition_api_routes.py -q`

### Task 4: Final Verification and Publish

- [ ] **Step 1: Run web acquisition tests**

Run: `$files = Get-ChildItem -LiteralPath tests -Filter 'test_web_acquisition_*.py' | ForEach-Object { $_.FullName }; pytest @files -q`

- [ ] **Step 2: Run full test suite**

Run: `pytest -q`

- [ ] **Step 3: Commit, push, create PR, and merge after confirming PR is mergeable**
