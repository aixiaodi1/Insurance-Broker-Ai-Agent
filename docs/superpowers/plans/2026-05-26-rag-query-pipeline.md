# RAG Query Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/agent/run` from a retrieval debug endpoint into a real RAG query pipeline with MiniMax answer generation.

**Architecture:** Keep FastAPI as the RAG service owner. Add small infrastructure adapters for rerank and chat generation, then orchestrate receive, intent analysis, retrieval, rerank, context packing, generation, citation verification, and final response inside `RagQueryService`.

**Tech Stack:** FastAPI, ChromaDB Python client, httpx, pytest, pytest-httpx, MiniMax OpenAI-compatible Chat Completions.

---

### Task 1: Add Query Pipeline Tests

**Files:**
- Create: `rag-backend/tests/test_rag_query_service.py`
- Modify: `rag-backend/tests/test_api_routes.py`

- [x] **Step 1: Write failing tests for RAG orchestration**

Cover intent analysis, retrieval top-k, rerank ordering, packed citation ids, MiniMax generator call through a fake, and citation verification.

- [x] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_rag_query_service.py -v`
Expected: fail because `app.services.rag_query_service` does not exist.

### Task 2: Add Reranker Adapter

**Files:**
- Create: `rag-backend/app/infrastructure/rerankers/base.py`
- Create: `rag-backend/app/infrastructure/rerankers/local_api.py`
- Create: `rag-backend/tests/test_local_reranker.py`

- [x] **Step 1: Write failing adapter tests**

Cover request shape, score sorting preservation from API response, top_k, retryable 5xx, non-retryable 4xx, and invalid JSON.

- [x] **Step 2: Implement adapter with `httpx`**

Use `POST {RERANK_API_BASE_URL}{RERANK_API_PATH}` with `{query, documents, model, top_k}`.

### Task 3: Add MiniMax Generator

**Files:**
- Create: `rag-backend/app/infrastructure/generators/base.py`
- Create: `rag-backend/app/infrastructure/generators/minimax.py`
- Create: `rag-backend/tests/test_minimax_generator.py`

- [x] **Step 1: Write failing generator tests**

Cover OpenAI-compatible request shape, `Authorization: Bearer`, answer parsing, usage parsing, 5xx retryable errors, and 4xx non-retryable errors.

- [x] **Step 2: Implement generator with `httpx`**

Use MiniMax model `MiniMax-M2.7` by default and `https://api.minimax.io/v1/chat/completions`.

### Task 4: Wire Service and Route

**Files:**
- Create: `rag-backend/app/services/rag_query_service.py`
- Modify: `rag-backend/app/config.py`
- Modify: `rag-backend/app/dependencies.py`
- Modify: `rag-backend/app/routers/agent.py`
- Modify: `rag-backend/app/infrastructure/vectorstores/base.py`
- Modify: `rag-backend/.env.example`
- Modify: `rag-backend/README.md`

- [x] **Step 1: Add settings and dependency factories**

Add rerank and LLM settings without committing secrets.

- [x] **Step 2: Replace route internals**

Keep `/agent/run` response compatible with frontend types.

- [x] **Step 3: Run targeted tests**

Run: `python -m pytest tests/test_rag_query_service.py tests/test_local_reranker.py tests/test_minimax_generator.py tests/test_api_routes.py -v`

### Task 5: Full Verification

**Files:**
- No production changes.

- [ ] **Step 1: Run backend tests**

Run: `python -m pytest -v`

- [ ] **Step 2: Report status**

Summarize implemented pipeline, tests run, and any environment setup still needed.
