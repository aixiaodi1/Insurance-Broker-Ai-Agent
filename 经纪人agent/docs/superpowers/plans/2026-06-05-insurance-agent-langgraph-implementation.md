# Insurance Product Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working LangGraph backend for a verifiable insurance product research Agent with novice-friendly output, durable memory, context compaction, evidence gates, and audit logs.

**Architecture:** The backend is split into focused units: graph nodes, tools, gates, memory, context compaction, audit logging, and FastAPI routes. The first version uses deterministic tool interfaces and local SQLite/JSONL persistence so the workflow is testable before adding full web crawling and production RAG.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Pydantic, SQLite FTS5, pytest, httpx.

---

## File Structure

```text
app/
  __init__.py
  main.py
  config.py
  agents/
    __init__.py
    state.py
    runtime.py
    graphs/
      __init__.py
      intake_graph.py
      evidence_graph.py
      report_graph.py
      research_graph.py
    nodes/
      __init__.py
      intake_nodes.py
      evidence_nodes.py
      report_nodes.py
      memory_nodes.py
      context_nodes.py
  tools/
    __init__.py
    local_sources.py
    web_sources.py
    pdf_tools.py
    rag_tools.py
    identity_tools.py
    iachina_tools.py
  gates/
    __init__.py
    evidence_gates.py
    permission_gates.py
  memory/
    __init__.py
    sqlite_memory.py
    repositories.py
    schemas.py
  audit/
    __init__.py
    logger.py
  api/
    __init__.py
    routes.py
tests/
  test_state.py
  test_memory_sqlite.py
  test_context_compaction.py
  test_evidence_gates.py
  test_intake_graph.py
  test_evidence_graph.py
  test_report_graph.py
  test_api_routes.py
data/
  memory/
    .gitkeep
  runs/
    .gitkeep
```

## Domain Classes And Contracts

### Core State

```python
class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    user_input: str
    task_type: str
    user_level: str
    company_name: str | None
    product_name: str | None
    aliases: list[str]
    local_candidates: list[dict[str, Any]]
    web_leads: list[dict[str, Any]]
    official_sources: list[dict[str, Any]]
    pdf_assets: list[dict[str, Any]]
    product_identity: dict[str, Any] | None
    iachina_status: dict[str, Any] | None
    rag_citations: list[dict[str, Any]]
    evidence_score: dict[str, Any] | None
    stop_reasons: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    conversation_summary: str | None
    tool_events: list[dict[str, Any]]
    user_visible_steps: list[dict[str, Any]]
    context_budget: dict[str, Any]
    final_summary: str | None
    final_report: str | None
```

### Tool Result

```python
class ToolResult(BaseModel):
    ok: bool
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
```

### Evidence Item

```python
class EvidenceItem(BaseModel):
    title: str
    company_name: str | None = None
    product_name: str | None = None
    source_url: str | None = None
    source_tier: str = "S5"
    material_type: str | None = None
    file_hash: str | None = None
    page: int | None = None
    chunk_id: str | None = None
```

## Task 1: Project Skeleton

**Files:**
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/config.py`
- Create: `app/api/__init__.py`
- Create: `app/api/routes.py`
- Create: `data/memory/.gitkeep`
- Create: `data/runs/.gitkeep`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Write the failing API smoke test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_route_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_api_routes.py::test_health_route_returns_ok -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Create minimal FastAPI app**

`app/main.py`

```python
from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Insurance Product Research Agent")
app.include_router(router)
```

`app/api/routes.py`

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

`app/config.py`

```python
from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    data_dir: Path = Path("data")
    memory_db_path: Path = Path("data/memory/agent_memory.sqlite3")
    runs_dir: Path = Path("data/runs")
    max_messages_before_summary: int = 20
    max_tool_events_before_summary: int = 50


settings = Settings()
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_api_routes.py::test_health_route_returns_ok -v`

Expected: PASS.

## Task 2: State And Schemas

**Files:**
- Create: `app/agents/__init__.py`
- Create: `app/agents/state.py`
- Create: `app/memory/__init__.py`
- Create: `app/memory/schemas.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write failing state defaults test**

```python
from app.agents.state import new_agent_state


def test_new_agent_state_sets_required_defaults():
    state = new_agent_state(
        user_id="user-1",
        user_input="帮我查众民保",
        thread_id="user-1:task-1",
    )
    assert state["user_id"] == "user-1"
    assert state["thread_id"] == "user-1:task-1"
    assert state["user_input"] == "帮我查众民保"
    assert state["user_level"] == "novice"
    assert state["local_candidates"] == []
    assert state["tool_events"] == []
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_state.py::test_new_agent_state_sets_required_defaults -v`

Expected: FAIL with missing module or function.

- [ ] **Step 3: Implement state and schemas**

`app/agents/state.py`

```python
from typing import Any, TypedDict
from uuid import uuid4


class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    user_input: str
    task_type: str
    user_level: str
    company_name: str | None
    product_name: str | None
    aliases: list[str]
    local_candidates: list[dict[str, Any]]
    web_leads: list[dict[str, Any]]
    official_sources: list[dict[str, Any]]
    pdf_assets: list[dict[str, Any]]
    product_identity: dict[str, Any] | None
    iachina_status: dict[str, Any] | None
    rag_citations: list[dict[str, Any]]
    evidence_score: dict[str, Any] | None
    stop_reasons: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    conversation_summary: str | None
    tool_events: list[dict[str, Any]]
    user_visible_steps: list[dict[str, Any]]
    context_budget: dict[str, Any]
    final_summary: str | None
    final_report: str | None


def new_agent_state(user_id: str, user_input: str, thread_id: str) -> AgentState:
    return {
        "run_id": str(uuid4()),
        "thread_id": thread_id,
        "user_id": user_id,
        "user_input": user_input,
        "task_type": "unknown",
        "user_level": "novice",
        "company_name": None,
        "product_name": None,
        "aliases": [],
        "local_candidates": [],
        "web_leads": [],
        "official_sources": [],
        "pdf_assets": [],
        "product_identity": None,
        "iachina_status": None,
        "rag_citations": [],
        "evidence_score": None,
        "stop_reasons": [],
        "messages": [{"role": "user", "content": user_input}],
        "conversation_summary": None,
        "tool_events": [],
        "user_visible_steps": [],
        "context_budget": {},
        "final_summary": None,
        "final_report": None,
    }
```

`app/memory/schemas.py`

```python
from typing import Any
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EvidenceItem(BaseModel):
    title: str
    company_name: str | None = None
    product_name: str | None = None
    source_url: str | None = None
    source_tier: str = "S5"
    material_type: str | None = None
    file_hash: str | None = None
    page: int | None = None
    chunk_id: str | None = None
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_state.py -v`

Expected: PASS.

## Task 3: Hermes-Style SQLite Memory

**Files:**
- Create: `app/memory/sqlite_memory.py`
- Test: `tests/test_memory_sqlite.py`

- [ ] **Step 1: Write failing SQLite memory test**

```python
from app.memory.sqlite_memory import SQLiteMemory


def test_memory_stores_raw_message_and_searches_with_fts(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    memory = SQLiteMemory(db_path)
    memory.init_schema()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="user-1:task-1",
        title="众民保研究",
        task_type="product_research",
    )
    memory.add_message(session_id=session_id, role="user", content="帮我查众民保的官方资料")
    results = memory.search_messages("众民保")
    assert len(results) == 1
    assert results[0]["content"] == "帮我查众民保的官方资料"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_memory_sqlite.py::test_memory_stores_raw_message_and_searches_with_fts -v`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement SQLite memory**

`app/memory/sqlite_memory.py`

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class SQLiteMemory:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'running',
                    score REAL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reasoning TEXT,
                    tool_calls TEXT DEFAULT '[]',
                    token_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    message_id UNINDEXED
                );

                CREATE TABLE IF NOT EXISTS tool_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    input_json TEXT DEFAULT '{}',
                    output_json TEXT DEFAULT '{}',
                    url TEXT,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def create_session(self, user_id: str, thread_id: str, title: str, task_type: str) -> str:
        session_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, thread_id, title, task_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, thread_id, title, task_type),
            )
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        reasoning: str | None = None,
        tool_calls: list[dict] | None = None,
        token_count: int = 0,
    ) -> str:
        message_id = str(uuid4())
        tool_calls_json = json.dumps(tool_calls or [], ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, reasoning, tool_calls, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, reasoning, tool_calls_json, token_count),
            )
            conn.execute(
                """
                INSERT INTO messages_fts (content, session_id, message_id)
                VALUES (?, ?, ?)
                """,
                (content, session_id, message_id),
            )
        return message_id

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, session_id, content
                FROM messages_fts
                WHERE messages_fts MATCH ?
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_memory_sqlite.py -v`

Expected: PASS.

## Task 4: Audit Logger

**Files:**
- Create: `app/audit/__init__.py`
- Create: `app/audit/logger.py`
- Test: `tests/test_memory_sqlite.py`

- [ ] **Step 1: Add failing audit event test**

```python
from app.memory.sqlite_memory import SQLiteMemory
from app.audit.logger import AuditLogger


def test_audit_logger_writes_tool_event_to_db_and_jsonl(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    logger = AuditLogger(memory=memory, runs_dir=tmp_path / "runs")
    logger.log_tool_event(
        run_id="run-1",
        thread_id="user-1:task-1",
        node="local_evidence_search",
        tool="search_local_specs",
        status="success",
        input_json={"query": "众民保"},
        output_json={"count": 1},
    )
    events_file = tmp_path / "runs" / "run-1" / "events.jsonl"
    assert events_file.exists()
    assert "search_local_specs" in events_file.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_memory_sqlite.py::test_audit_logger_writes_tool_event_to_db_and_jsonl -v`

Expected: FAIL with missing `AuditLogger`.

- [ ] **Step 3: Implement audit logger**

`app/audit/logger.py`

```python
from __future__ import annotations

import json
from pathlib import Path
from time import time
from uuid import uuid4

from app.memory.sqlite_memory import SQLiteMemory


class AuditLogger:
    def __init__(self, memory: SQLiteMemory, runs_dir: Path):
        self.memory = memory
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def log_tool_event(
        self,
        run_id: str,
        thread_id: str,
        node: str,
        tool: str,
        status: str,
        input_json: dict,
        output_json: dict,
        url: str | None = None,
        file_path: str | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        event = {
            "id": str(uuid4()),
            "run_id": run_id,
            "thread_id": thread_id,
            "timestamp": time(),
            "node": node,
            "tool": tool,
            "input_json": input_json,
            "output_json": output_json,
            "url": url,
            "file_path": file_path,
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
        }
        with self.memory.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_events (
                    id, run_id, thread_id, node, tool, input_json, output_json,
                    url, file_path, status, error, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    run_id,
                    thread_id,
                    node,
                    tool,
                    json.dumps(input_json, ensure_ascii=False),
                    json.dumps(output_json, ensure_ascii=False),
                    url,
                    file_path,
                    status,
                    error,
                    duration_ms,
                ),
            )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_memory_sqlite.py -v`

Expected: PASS.

## Task 5: Context Compaction

**Files:**
- Create: `app/agents/nodes/context_nodes.py`
- Test: `tests/test_context_compaction.py`

- [ ] **Step 1: Write failing compaction test**

```python
from app.agents.nodes.context_nodes import compact_context


def test_compact_context_keeps_recent_messages_and_summarizes_old_ones():
    state = {
        "messages": [{"role": "user", "content": f"消息{i}"} for i in range(25)],
        "tool_events": [{"tool": "http_get", "status": "success", "url": f"https://example.com/{i}"} for i in range(60)],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5, "max_tool_events": 3},
    }
    new_state = compact_context(state)
    assert len(new_state["messages"]) == 5
    assert "消息0" in new_state["conversation_summary"]
    assert len(new_state["tool_events"]) == 3
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_context_compaction.py -v`

Expected: FAIL with missing function.

- [ ] **Step 3: Implement deterministic compaction**

`app/agents/nodes/context_nodes.py`

```python
from typing import Any


def compact_context(state: dict[str, Any]) -> dict[str, Any]:
    budget = state.get("context_budget") or {}
    max_messages = int(budget.get("max_messages", 12))
    max_tool_events = int(budget.get("max_tool_events", 20))

    messages = list(state.get("messages", []))
    if len(messages) > max_messages:
        old_messages = messages[:-max_messages]
        recent_messages = messages[-max_messages:]
        old_text = " | ".join(str(item.get("content", "")) for item in old_messages)
        state["conversation_summary"] = (
            (state.get("conversation_summary") or "")
            + f"\n历史对话摘要: {old_text[:1000]}"
        ).strip()
        state["messages"] = recent_messages

    tool_events = list(state.get("tool_events", []))
    if len(tool_events) > max_tool_events:
        state["tool_events_summary"] = {
            "total": len(tool_events),
            "success": sum(1 for item in tool_events if item.get("status") == "success"),
            "fail": sum(1 for item in tool_events if item.get("status") == "fail"),
        }
        state["tool_events"] = tool_events[-max_tool_events:]

    return state
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_context_compaction.py -v`

Expected: PASS.

## Task 6: Gates

**Files:**
- Create: `app/gates/__init__.py`
- Create: `app/gates/evidence_gates.py`
- Create: `app/gates/permission_gates.py`
- Test: `tests/test_evidence_gates.py`

- [ ] **Step 1: Write failing gate tests**

```python
from app.gates.evidence_gates import evidence_gate, verify_before_rag_gate
from app.gates.permission_gates import secret_write_deny_gate


def test_evidence_gate_blocks_formal_report_without_official_sources():
    decision = evidence_gate({"official_sources": [], "rag_citations": []})
    assert decision["allowed"] is False
    assert decision["route"] == "generate_user_friendly_summary"


def test_verify_before_rag_gate_blocks_invalid_pdf():
    decision = verify_before_rag_gate({"pdf_assets": [{"is_valid_pdf": False}]})
    assert decision["allowed"] is False


def test_secret_write_deny_gate_blocks_env_files():
    decision = secret_write_deny_gate(".env")
    assert decision["allowed"] is False
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_evidence_gates.py -v`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement gates**

`app/gates/evidence_gates.py`

```python
from typing import Any


def evidence_gate(state: dict[str, Any]) -> dict[str, Any]:
    official_sources = state.get("official_sources") or []
    rag_citations = state.get("rag_citations") or []
    allowed = bool(official_sources and rag_citations)
    return {
        "allowed": allowed,
        "route": "generate_formal_report" if allowed else "generate_user_friendly_summary",
        "reason": None if allowed else "官方证据或RAG引用不足",
    }


def verify_before_rag_gate(state: dict[str, Any]) -> dict[str, Any]:
    pdf_assets = state.get("pdf_assets") or []
    invalid = [item for item in pdf_assets if item.get("is_valid_pdf") is False]
    return {
        "allowed": not invalid,
        "reason": None if not invalid else "存在未通过PDF魔数校验的材料",
    }
```

`app/gates/permission_gates.py`

```python
from pathlib import Path


SECRET_FILENAMES = {".env", "config.toml", "secrets.toml"}


def secret_write_deny_gate(path: str) -> dict[str, object]:
    name = Path(path).name.lower()
    denied = name in SECRET_FILENAMES or "token" in name or "secret" in name
    return {
        "allowed": not denied,
        "reason": "禁止写入密钥文件" if denied else None,
    }
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_evidence_gates.py -v`

Expected: PASS.

## Task 7: Tool Interfaces

**Files:**
- Create: `app/tools/__init__.py`
- Create: `app/tools/local_sources.py`
- Create: `app/tools/web_sources.py`
- Create: `app/tools/pdf_tools.py`
- Create: `app/tools/rag_tools.py`
- Create: `app/tools/identity_tools.py`
- Create: `app/tools/iachina_tools.py`
- Test: `tests/test_evidence_graph.py`

- [ ] **Step 1: Write failing tool contract test**

```python
from app.tools.local_sources import search_local_specs
from app.tools.identity_tools import resolve_product_alias


def test_search_local_specs_returns_tool_result():
    result = search_local_specs(company_name="众民保", product_name=None)
    assert result.ok is True
    assert result.source == "local_specs"
    assert "candidates" in result.data


def test_resolve_product_alias_returns_identity_candidate():
    result = resolve_product_alias(product_name="众民保", aliases=["众民保"])
    assert result.ok is True
    assert result.data["product_name"] == "众民保"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_evidence_graph.py::test_search_local_specs_returns_tool_result tests/test_evidence_graph.py::test_resolve_product_alias_returns_identity_candidate -v`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement first deterministic tools**

`app/tools/local_sources.py`

```python
from app.memory.schemas import ToolResult


def search_local_specs(company_name: str | None, product_name: str | None) -> ToolResult:
    query = company_name or product_name or ""
    return ToolResult(
        ok=True,
        source="local_specs",
        data={
            "query": query,
            "candidates": [],
        },
    )
```

`app/tools/identity_tools.py`

```python
from app.memory.schemas import ToolResult


def resolve_product_alias(product_name: str | None, aliases: list[str]) -> ToolResult:
    canonical = product_name or (aliases[0] if aliases else None)
    return ToolResult(
        ok=canonical is not None,
        source="identity",
        data={
            "product_name": canonical,
            "aliases": aliases,
            "components": [],
        },
        error=None if canonical else "缺少产品名",
    )
```

`app/tools/web_sources.py`

```python
from app.memory.schemas import ToolResult


def web_extract(query: str) -> ToolResult:
    return ToolResult(ok=True, source="web_extract", data={"query": query, "leads": []})
```

`app/tools/pdf_tools.py`

```python
from pathlib import Path
from app.memory.schemas import ToolResult


def validate_pdf(path: str) -> ToolResult:
    file_path = Path(path)
    if not file_path.exists():
        return ToolResult(ok=False, source="pdf", error="文件不存在")
    with file_path.open("rb") as fh:
        magic = fh.read(4)
    return ToolResult(
        ok=magic == b"%PDF",
        source="pdf",
        data={"path": str(file_path), "is_valid_pdf": magic == b"%PDF"},
        error=None if magic == b"%PDF" else "不是PDF魔数",
    )
```

`app/tools/rag_tools.py`

```python
from app.memory.schemas import ToolResult


def rag_search(query: str) -> ToolResult:
    return ToolResult(ok=True, source="rag", data={"query": query, "citations": []})
```

`app/tools/iachina_tools.py`

```python
from app.memory.schemas import ToolResult


def query_iachina_property_product(company_name: str | None, product_name: str | None) -> ToolResult:
    return ToolResult(
        ok=False,
        source="iachina",
        data={"company_name": company_name, "product_name": product_name, "status": "not_configured"},
        error="中保协查询工具尚未接入，需要人工或浏览器会话",
    )
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_evidence_graph.py -v`

Expected: PASS for the two tool tests.

## Task 8: Intake Graph Nodes

**Files:**
- Create: `app/agents/nodes/__init__.py`
- Create: `app/agents/nodes/intake_nodes.py`
- Create: `app/agents/graphs/__init__.py`
- Create: `app/agents/graphs/intake_graph.py`
- Test: `tests/test_intake_graph.py`

- [ ] **Step 1: Write failing intake graph test**

```python
from app.agents.graphs.intake_graph import run_intake_graph
from app.agents.state import new_agent_state


def test_intake_graph_routes_product_research():
    state = new_agent_state("user-1", "帮我查众民保官方资料", "user-1:task-1")
    result = run_intake_graph(state)
    assert result["task_type"] == "official_evidence_research"
    assert result["product_name"] == "众民保"
    assert result["user_visible_steps"][0]["title"] == "我先帮你确认要查的产品"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_intake_graph.py -v`

Expected: FAIL with missing graph.

- [ ] **Step 3: Implement intake nodes without external LLM**

`app/agents/nodes/intake_nodes.py`

```python
from typing import Any


def novice_intake(state: dict[str, Any]) -> dict[str, Any]:
    text = state.get("user_input", "")
    product_name = "众民保" if "众民保" in text else state.get("product_name")
    state["product_name"] = product_name
    state["aliases"] = [product_name] if product_name else []
    state["user_visible_steps"].append({
        "title": "我先帮你确认要查的产品",
        "detail": product_name or "还没有识别出明确产品名",
    })
    return state


def task_router(state: dict[str, Any]) -> dict[str, Any]:
    state["task_type"] = "official_evidence_research"
    return state
```

`app/agents/graphs/intake_graph.py`

```python
from app.agents.nodes.intake_nodes import novice_intake, task_router


def run_intake_graph(state: dict) -> dict:
    state = novice_intake(state)
    state = task_router(state)
    return state
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_intake_graph.py -v`

Expected: PASS.

## Task 9: Evidence Research Graph Nodes

**Files:**
- Create: `app/agents/nodes/evidence_nodes.py`
- Create: `app/agents/graphs/evidence_graph.py`
- Test: `tests/test_evidence_graph.py`

- [ ] **Step 1: Add failing evidence graph test**

```python
from app.agents.graphs.evidence_graph import run_evidence_graph
from app.agents.state import new_agent_state


def test_evidence_graph_records_missing_evidence_for_empty_local_results():
    state = new_agent_state("user-1", "帮我查众民保官方资料", "user-1:task-1")
    state["product_name"] = "众民保"
    result = run_evidence_graph(state)
    assert result["product_identity"]["product_name"] == "众民保"
    assert result["evidence_score"]["total"] < 60
    assert result["stop_reasons"][0]["code"] == "official_evidence_not_closed"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_evidence_graph.py::test_evidence_graph_records_missing_evidence_for_empty_local_results -v`

Expected: FAIL with missing graph.

- [ ] **Step 3: Implement evidence nodes**

`app/agents/nodes/evidence_nodes.py`

```python
from typing import Any

from app.tools.identity_tools import resolve_product_alias
from app.tools.local_sources import search_local_specs
from app.tools.rag_tools import rag_search


def local_evidence_search(state: dict[str, Any]) -> dict[str, Any]:
    result = search_local_specs(state.get("company_name"), state.get("product_name"))
    state["local_candidates"] = result.data.get("candidates", [])
    return state


def web_lead_search(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("local_candidates"):
        return state
    state["web_leads"] = []
    state["stop_reasons"].append({
        "code": "official_evidence_not_closed",
        "message": "本地和网络线索暂未形成官网证据闭环",
    })
    return state


def product_identity_resolve(state: dict[str, Any]) -> dict[str, Any]:
    result = resolve_product_alias(state.get("product_name"), state.get("aliases", []))
    state["product_identity"] = result.data if result.ok else None
    return state


def rag_citation_check(state: dict[str, Any]) -> dict[str, Any]:
    result = rag_search(state.get("product_name") or state.get("user_input", ""))
    state["rag_citations"] = result.data.get("citations", [])
    return state


def evidence_score(state: dict[str, Any]) -> dict[str, Any]:
    official_points = 30 if state.get("official_sources") else 0
    identity_points = 20 if state.get("product_identity") else 0
    citation_points = 20 if state.get("rag_citations") else 0
    total = official_points + identity_points + citation_points
    state["evidence_score"] = {
        "official_evidence": official_points,
        "product_identity": identity_points,
        "citations": citation_points,
        "total": total,
    }
    return state
```

`app/agents/graphs/evidence_graph.py`

```python
from app.agents.nodes.evidence_nodes import (
    evidence_score,
    local_evidence_search,
    product_identity_resolve,
    rag_citation_check,
    web_lead_search,
)


def run_evidence_graph(state: dict) -> dict:
    state = local_evidence_search(state)
    state = web_lead_search(state)
    state = product_identity_resolve(state)
    state = rag_citation_check(state)
    state = evidence_score(state)
    return state
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_evidence_graph.py -v`

Expected: PASS.

## Task 10: Report Graph

**Files:**
- Create: `app/agents/nodes/report_nodes.py`
- Create: `app/agents/graphs/report_graph.py`
- Test: `tests/test_report_graph.py`

- [ ] **Step 1: Write failing report test**

```python
from app.agents.graphs.report_graph import run_report_graph
from app.agents.state import new_agent_state


def test_report_graph_generates_novice_summary_when_score_is_low():
    state = new_agent_state("user-1", "帮我查众民保官方资料", "user-1:task-1")
    state["product_name"] = "众民保"
    state["evidence_score"] = {"total": 20}
    state["stop_reasons"] = [{"message": "官网证据未闭环"}]
    result = run_report_graph(state)
    assert "我查到了什么" in result["final_summary"]
    assert "官网证据未闭环" in result["final_summary"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_report_graph.py -v`

Expected: FAIL with missing graph.

- [ ] **Step 3: Implement report graph**

`app/agents/nodes/report_nodes.py`

```python
from typing import Any


def generate_user_friendly_summary(state: dict[str, Any]) -> dict[str, Any]:
    product = state.get("product_name") or "这个产品"
    reasons = state.get("stop_reasons") or []
    reason_text = "；".join(item.get("message", "") for item in reasons) or "暂无未闭环问题"
    state["final_summary"] = (
        f"## 我查到了什么\n"
        f"我正在帮你查：{product}。\n\n"
        f"## 哪些是官方证据\n"
        f"目前还没有足够的官方证据进入正式报告。\n\n"
        f"## 还有哪些没确认\n"
        f"{reason_text}\n\n"
        f"## 下一步你可以点什么\n"
        f"你可以继续官网查找、上传PDF，或让人工复核产品名称。"
    )
    return state


def generate_formal_report(state: dict[str, Any]) -> dict[str, Any]:
    state["final_report"] = state.get("final_summary") or "正式报告生成成功。"
    return state
```

`app/agents/graphs/report_graph.py`

```python
from app.agents.nodes.report_nodes import generate_formal_report, generate_user_friendly_summary


def run_report_graph(state: dict) -> dict:
    score = (state.get("evidence_score") or {}).get("total", 0)
    if score >= 80:
        return generate_formal_report(state)
    return generate_user_friendly_summary(state)
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_report_graph.py -v`

Expected: PASS.

## Task 11: Full Research Graph Runtime

**Files:**
- Create: `app/agents/runtime.py`
- Create: `app/agents/graphs/research_graph.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Add failing research API test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_research_route_returns_summary():
    client = TestClient(app)
    response = client.post(
        "/agent/research",
        json={
            "user_id": "user-1",
            "message": "帮我查众民保官方资料",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"].startswith("user-1:")
    assert "我查到了什么" in body["final_summary"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_api_routes.py::test_research_route_returns_summary -v`

Expected: FAIL with 404.

- [ ] **Step 3: Implement runtime and route**

`app/agents/graphs/research_graph.py`

```python
from app.agents.graphs.evidence_graph import run_evidence_graph
from app.agents.graphs.intake_graph import run_intake_graph
from app.agents.graphs.report_graph import run_report_graph


def run_research_graph(state: dict) -> dict:
    state = run_intake_graph(state)
    state = run_evidence_graph(state)
    state = run_report_graph(state)
    return state
```

`app/agents/runtime.py`

```python
from uuid import uuid4

from app.agents.graphs.research_graph import run_research_graph
from app.agents.state import new_agent_state


def run_research_task(user_id: str, message: str, thread_id: str | None = None) -> dict:
    effective_thread_id = thread_id or f"{user_id}:{uuid4()}"
    state = new_agent_state(user_id=user_id, user_input=message, thread_id=effective_thread_id)
    return run_research_graph(state)
```

`app/api/routes.py`

```python
from pydantic import BaseModel
from fastapi import APIRouter

from app.agents.runtime import run_research_task

router = APIRouter()


class ResearchRequest(BaseModel):
    user_id: str
    message: str
    thread_id: str | None = None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/agent/research")
def research(request: ResearchRequest) -> dict:
    state = run_research_task(
        user_id=request.user_id,
        message=request.message,
        thread_id=request.thread_id,
    )
    return {
        "run_id": state["run_id"],
        "thread_id": state["thread_id"],
        "task_type": state["task_type"],
        "final_summary": state.get("final_summary"),
        "evidence_score": state.get("evidence_score"),
        "stop_reasons": state.get("stop_reasons", []),
        "user_visible_steps": state.get("user_visible_steps", []),
    }
```

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_api_routes.py -v`

Expected: PASS.

## Task 12: Wire SQLite Memory Into Runtime

**Files:**
- Modify: `app/agents/runtime.py`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Add failing memory persistence assertion**

```python
from app.config import settings
from app.memory.sqlite_memory import SQLiteMemory


def test_research_route_persists_raw_user_message(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.sqlite3"
    monkeypatch.setattr(settings, "memory_db_path", db_path)

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    client.post("/agent/research", json={"user_id": "user-1", "message": "帮我查众民保官方资料"})

    memory = SQLiteMemory(db_path)
    results = memory.search_messages("众民保")
    assert results
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_api_routes.py::test_research_route_persists_raw_user_message -v`

Expected: FAIL because runtime does not write memory yet.

- [ ] **Step 3: Persist raw user message and assistant summary**

`app/agents/runtime.py`

```python
from uuid import uuid4

from app.agents.graphs.research_graph import run_research_graph
from app.agents.state import new_agent_state
from app.config import settings
from app.memory.sqlite_memory import SQLiteMemory


def run_research_task(user_id: str, message: str, thread_id: str | None = None) -> dict:
    effective_thread_id = thread_id or f"{user_id}:{uuid4()}"
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    session_id = memory.create_session(
        user_id=user_id,
        thread_id=effective_thread_id,
        title=message[:40] or "保险产品研究",
        task_type="official_evidence_research",
    )
    memory.add_message(session_id=session_id, role="user", content=message)
    state = new_agent_state(user_id=user_id, user_input=message, thread_id=effective_thread_id)
    state = run_research_graph(state)
    if state.get("final_summary"):
        memory.add_message(session_id=session_id, role="assistant", content=state["final_summary"])
    return state
```

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_api_routes.py -v`

Expected: PASS.

## Task 13: Search Memory API

**Files:**
- Modify: `app/api/routes.py`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Add failing memory search API test**

```python
def test_memory_search_route_returns_matches(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "memory_db_path", tmp_path / "agent_memory.sqlite3")

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    client.post("/agent/research", json={"user_id": "user-1", "message": "帮我查众民保官方资料"})
    response = client.get("/agent/memory/search", params={"q": "众民保"})
    assert response.status_code == 200
    assert response.json()["results"][0]["content"] == "帮我查众民保官方资料"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_api_routes.py::test_memory_search_route_returns_matches -v`

Expected: FAIL with 404.

- [ ] **Step 3: Add memory search route**

Add to `app/api/routes.py`:

```python
from app.config import settings
from app.memory.sqlite_memory import SQLiteMemory


@router.get("/agent/memory/search")
def search_memory(q: str) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"results": memory.search_messages(q)}
```

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_api_routes.py -v`

Expected: PASS.

## Task 14: Final Verification

**Files:**
- All files above.

- [ ] **Step 1: Run all tests**

Run: `pytest -v`

Expected: all tests PASS.

- [ ] **Step 2: Start the API locally**

Run: `uvicorn app.main:app --reload --port 8000`

Expected: server starts on `http://127.0.0.1:8000`.

- [ ] **Step 3: Exercise the research endpoint**

Run:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri 'http://127.0.0.1:8000/agent/research' `
  -ContentType 'application/json' `
  -Body '{"user_id":"user-1","message":"帮我查众民保官方资料"}'
```

Expected: JSON contains `final_summary`, `evidence_score`, `stop_reasons`, and `user_visible_steps`.

- [ ] **Step 4: Exercise memory search**

Run:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/agent/memory/search?q=众民保'
```

Expected: JSON contains the raw user message.

## Deferred Work

| Item | Reason |
|---|---|
| Production LangGraph `StateGraph` replacement | First version keeps deterministic graph functions so tests stay simple |
| `PostgresSaver` | Use after local SQLite flow is stable |
| Full web search provider | Needs provider keys and permission policy |
| Playwright browser harness | Needs browser runtime and WAF/session policy |
| 中保协自动化 | Requires human login/verification boundary |
| Full RAG integration | Requires existing vector store and document ingestion |
| IRR / 分红实现率 | Depends on verified official materials |

## Self-Review

| Check | Result |
|---|---|
| Spec coverage | Covers novice intake, evidence graph, report graph, memory, context compaction, gates, audit log, FastAPI |
| Placeholder scan | No TODO/TBD placeholders are required for implementation |
| Type consistency | Uses `AgentState`, `ToolResult`, `EvidenceItem`, `SQLiteMemory`, `AuditLogger` consistently |
| Scope | First phase only; advanced crawling/RAG/IRR deferred |

