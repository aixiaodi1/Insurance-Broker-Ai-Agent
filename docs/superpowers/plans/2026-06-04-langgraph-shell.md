# LangGraph Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LangGraph orchestration shell for the existing RAG agent while preserving the current FastAPI and workbench response contract.

**Architecture:** Introduce `ResearchAgentGraph` as a thin graph runner behind `/agent/run_v2`. The graph initially delegates to the existing `RagQueryService.run()` so the behavior stays stable, while exposing a LangGraph-compiled node path and an explicit future extension point for `insurance_harness` tools.

**Tech Stack:** Python 3.11+, FastAPI, pytest, LangGraph, existing `RagQueryService`, Next.js workbench response schema.

---

## File Structure

- Create `rag-backend/app/agents/__init__.py`: package marker for graph modules.
- Create `rag-backend/app/agents/research_graph.py`: `ResearchAgentGraph`, graph state type, graph construction, and `run()` method.
- Modify `rag-backend/app/dependencies.py`: add `get_research_agent_graph()`.
- Modify `rag-backend/app/routers/agent.py`: make `/agent/run_v2` depend on the graph while `/agent/run` stays on `RagQueryService`.
- Modify `rag-backend/pyproject.toml`: add `langgraph`.
- Create `rag-backend/tests/test_research_graph.py`: graph smoke tests with a fake service.
- Modify `rag-backend/tests/test_api_routes.py`: add route test proving `/agent/run_v2` uses graph dependency.

## Task 1: Graph Smoke Test

**Files:**
- Create: `rag-backend/tests/test_research_graph.py`
- Create after red: `rag-backend/app/agents/__init__.py`
- Create after red: `rag-backend/app/agents/research_graph.py`

- [x] **Step 1: Write the failing test**

```python
from app.agents.research_graph import ResearchAgentGraph


class FakeRagQueryService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        self.calls.append(
            {
                "prompt": prompt,
                "collection": collection,
                "agent_id": agent_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "collected_vars": collected_vars,
            }
        )
        return {
            "id": "run_fake",
            "mode": "real",
            "prompt": prompt,
            "status": "succeeded",
            "nodes": [{"id": "receive_input", "status": "succeeded"}],
            "events": [{"id": "evt_receive_input", "nodeId": "receive_input"}],
            "toolCalls": [],
            "vectorMatches": [],
            "requestJson": {"prompt": prompt},
            "responseJson": {"collection": collection},
            "finalAnswer": "ok",
        }


def test_research_graph_delegates_to_rag_service_and_preserves_response() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(service)

    result = graph.run(
        prompt=" 查一下等待期 ",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        user_id="user_1",
        collected_vars={"age": 30},
    )

    assert result["id"] == "run_fake"
    assert result["finalAnswer"] == "ok"
    assert result["nodes"][0]["id"] == "receive_input"
    assert service.calls == [
        {
            "prompt": " 查一下等待期 ",
            "collection": "guides",
            "agent_id": "research-agent",
            "thread_id": "thread_1",
            "user_id": "user_1",
            "collected_vars": {"age": 30},
        }
    ]
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
cd rag-backend
python -m pytest tests/test_research_graph.py -v
```

Expected: FAIL because `app.agents.research_graph` does not exist.

- [x] **Step 3: Write minimal implementation**

Create `app/agents/__init__.py`:

```python
"""Agent graph modules."""
```

Create `app/agents/research_graph.py`:

```python
from typing import Any, NotRequired, Protocol, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    StateGraph = None


class RagRunner(Protocol):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict: ...


class ResearchGraphState(TypedDict):
    prompt: str
    collection: str
    agent_id: str
    thread_id: str | None
    user_id: str
    collected_vars: dict
    response: NotRequired[dict[str, Any]]


class ResearchAgentGraph:
    def __init__(self, rag_query_service: RagRunner) -> None:
        self._rag_query_service = rag_query_service
        self._graph = self._build_graph()

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        state: ResearchGraphState = {
            "prompt": prompt,
            "collection": collection,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "collected_vars": collected_vars or {},
        }
        result = self._graph.invoke(state) if self._graph is not None else self._run_existing_flow(state)
        return result["response"]

    def _build_graph(self):
        if StateGraph is None:
            return None
        graph = StateGraph(ResearchGraphState)
        graph.add_node("run_existing_rag_flow", self._run_existing_flow)
        graph.set_entry_point("run_existing_rag_flow")
        graph.add_edge("run_existing_rag_flow", END)
        return graph.compile()

    def _run_existing_flow(self, state: ResearchGraphState) -> ResearchGraphState:
        response = self._rag_query_service.run(
            prompt=state["prompt"],
            collection=state["collection"],
            agent_id=state["agent_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            collected_vars=state["collected_vars"],
        )
        return {**state, "response": response}
```

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
cd rag-backend
python -m pytest tests/test_research_graph.py -v
```

Expected: PASS.

## Task 2: Dependency and Route Wiring

**Files:**
- Modify: `rag-backend/app/dependencies.py`
- Modify: `rag-backend/app/routers/agent.py`
- Modify: `rag-backend/tests/test_api_routes.py`

- [x] **Step 1: Write the failing route test**

Append to `tests/test_api_routes.py`:

```python
def test_run_v2_uses_research_agent_graph_dependency() -> None:
    from app.dependencies import get_research_agent_graph

    class FakeResearchGraph:
        def run(
            self,
            prompt: str,
            collection: str,
            agent_id: str,
            thread_id: str | None,
            user_id: str = "default",
            collected_vars: dict | None = None,
        ) -> dict:
            return {
                "id": "run_graph",
                "mode": "real",
                "prompt": prompt,
                "status": "succeeded",
                "nodes": [{"id": "graph_node", "status": "succeeded"}],
                "events": [{"id": "evt_graph_node", "nodeId": "graph_node"}],
                "toolCalls": [],
                "vectorMatches": [],
                "requestJson": {"prompt": prompt},
                "responseJson": {"collection": collection, "userId": user_id},
                "finalAnswer": "graph answer",
            }

    client = make_client({get_research_agent_graph: lambda: FakeResearchGraph()})

    response = client.post(
        "/agent/run_v2",
        json={
            "prompt": "等待期是多少",
            "agentId": "research-agent",
            "threadId": "thread_graph",
            "collection": "guides",
            "userId": "user_graph",
            "collectedVars": {"age": 30},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "run_graph"
    assert body["finalAnswer"] == "graph answer"
    assert body["nodes"][0]["id"] == "graph_node"
    assert body["responseJson"] == {"collection": "guides", "userId": "user_graph"}
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
cd rag-backend
python -m pytest tests/test_api_routes.py::test_run_v2_uses_research_agent_graph_dependency -v
```

Expected: FAIL because `get_research_agent_graph` does not exist or `/run_v2` does not use it.

- [x] **Step 3: Wire dependency and route**

In `app/dependencies.py`, import and add:

```python
from app.agents.research_graph import ResearchAgentGraph
```

```python
def get_research_agent_graph() -> ResearchAgentGraph:
    return ResearchAgentGraph(get_rag_query_service())
```

In `app/routers/agent.py`, import:

```python
from app.agents.research_graph import ResearchAgentGraph
from app.dependencies import get_research_agent_graph
```

Change only `run_agent_v2` to depend on and call the graph:

```python
def run_agent_v2(
    request: AgentRunV2Request,
    research_agent_graph: ResearchAgentGraph = Depends(get_research_agent_graph),
    semaphore: threading.Semaphore = Depends(get_llm_semaphore),
) -> dict:
    """LangGraph-backed hybrid retrieval agent."""
    if not semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="服务繁忙，请稍后重试")
    try:
        return research_agent_graph.run(
            prompt=request.prompt,
            collection=request.collection,
            agent_id=request.agent_id,
            thread_id=request.thread_id,
            user_id=request.user_id,
            collected_vars=request.collected_vars,
        )
    ...
```

- [x] **Step 4: Run route test to verify it passes**

Run:

```bash
cd rag-backend
python -m pytest tests/test_api_routes.py::test_run_v2_uses_research_agent_graph_dependency -v
```

Expected: PASS.

## Task 3: LangGraph Dependency

**Files:**
- Modify: `rag-backend/pyproject.toml`

- [x] **Step 1: Write dependency expectation test**

Run:

```bash
cd rag-backend
python -c "import langgraph; print(langgraph.__name__)"
```

Expected before dependency installation: may FAIL if LangGraph is not installed.

- [x] **Step 2: Add dependency**

Add `"langgraph",` to the `[project].dependencies` array in `pyproject.toml`.

- [x] **Step 3: Install editable package dependencies if needed**

Run:

```bash
cd rag-backend
python -m pip install -e .
```

Expected: install succeeds and includes `langgraph`.

- [x] **Step 4: Verify import**

Run:

```bash
cd rag-backend
python -c "import langgraph; print(langgraph.__name__)"
```

Expected: prints `langgraph`.

## Task 4: Focused Regression

**Files:**
- No new files.

- [x] **Step 1: Run graph and route tests**

Run:

```bash
cd rag-backend
python -m pytest tests/test_research_graph.py tests/test_api_routes.py::test_run_v2_uses_research_agent_graph_dependency -v
```

Expected: PASS.

- [x] **Step 2: Run existing RAG and calculation tests**

Run:

```bash
cd rag-backend
python -m pytest tests/test_rag_query_service.py tests/test_calculation_flow.py -v
```

Expected: PASS.

- [x] **Step 3: Run backend test suite**

Run:

```bash
cd rag-backend
python -m pytest -q
```

Expected: PASS or report any pre-existing environment dependency failures with exact failing tests.

## Self-Review

- Spec coverage: graph service, route dependency, dependency declaration, response compatibility, claim-flow preservation through delegation, and future `insurance_harness` extension point are covered.
- Placeholder scan: no placeholder-only implementation steps remain.
- Type consistency: `ResearchAgentGraph.run()` matches `RagQueryService.run()` parameters plus `user_id` and `collected_vars`, matching `/agent/run_v2`.
