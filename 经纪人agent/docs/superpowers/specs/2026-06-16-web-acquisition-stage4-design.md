# Web Acquisition Stage 4 Design

## Context

Stages 1-3 already provide safe HTTP, deterministic browser, browser-use, and harness acquisition layers. Stage 4 wires those layers into a backend-only service with persistence and FastAPI routes.

## Design

`WebAcquisitionService` is the single orchestration entry point. It accepts the design contract parameters, creates a persisted task, runs the requested strategy, persists the final `AcquisitionResult`, and returns the task ID with the result.

The default `auto` strategy runs layers in this order: HTTP, Playwright, browser-use, harness. It stops on the first successful result. Explicit strategies run only their matching layer. A layer failure is recorded as structured errors and steps; useful partial data remains persisted.

`SQLiteAcquisitionStore` owns the acquisition schema:

- `acquisition_tasks`
- `acquisition_steps`
- `discovered_links`
- `downloaded_files`
- `site_harnesses`

The store persists a compact JSON result plus normalized step, link, and file rows so API callers can fetch the full task or focused step/file views.

FastAPI exposes backend-only routes:

- `POST /web-acquisition/run`
- `GET /web-acquisition/tasks/{task_id}`
- `GET /web-acquisition/tasks/{task_id}/steps`
- `GET /web-acquisition/tasks/{task_id}/files`

The first implementation runs synchronously inside the request and returns a persisted task ID plus the final status/result. No frontend entry point is added.

## Error Handling

The service records task status as `succeeded` or `failed`. Unexpected orchestration exceptions are converted to an `AcquisitionResult` with `strategy_used="none"` and an `orchestration_error` entry.

## Testing

Tests cover storage schema/persistence, service strategy routing and persistence, and FastAPI `TestClient` route behavior using fake fetchers and temporary SQLite paths.
