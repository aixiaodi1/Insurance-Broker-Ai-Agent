# LangGraph Shell Design

## Context

The current backend exposes `/agent/run` and `/agent/run_v2` from FastAPI. Both routes call `RagQueryService.run()`, which currently owns orchestration, retrieval, answer generation, citation checks, claim-calculation branching, and trace response construction.

The frontend workbench already expects a trace-shaped response with nodes, events, tool calls, vector matches, citations, and a final answer. That response shape should remain stable.

The goal of this phase is to add LangGraph as the orchestration layer without changing the business behavior yet. `insurance_harness` will be reserved as a future tool library integration point, but this phase does not require wiring its concrete tools.

## Goals

- Add a LangGraph shell around the existing RAG flow.
- Preserve the FastAPI gateway role and current frontend response contract.
- Keep current retrieval, reranking, generation, citation verification, and claim calculation behavior intact.
- Make future `insurance_harness` tools easy to attach as graph nodes or node-internal tools.
- Reduce risk by starting with a thin graph wrapper instead of rewriting the whole agent.

## Non-Goals

- Do not build the full insurance product research workflow yet.
- Do not add web search, official PDF verification, IAChina registration lookup, or browser automation in this phase.
- Do not redesign the frontend workbench response model.
- Do not migrate all private methods out of `RagQueryService` at once.
- Do not make C-end insurance purchase recommendations or recommendation-oriented prompts.

## Architecture

FastAPI remains the API gateway. A new graph service sits behind the `/agent/run_v2` route:

```text
Next.js workbench
  -> FastAPI /agent/run_v2
  -> ResearchAgentGraph
  -> existing RAG services and helper methods
  -> current AgentRun JSON response
```

The first graph implementation should live in:

```text
rag-backend/app/agents/research_graph.py
```

Dependency construction should be exposed through:

```text
rag-backend/app/dependencies.py
```

`RagQueryService` remains the underlying capability provider for the first phase. The graph calls its existing helpers where practical, then later phases can move those helpers into smaller services.

## Graph State

The graph state should be a typed dictionary or Pydantic-compatible state object with these fields:

- `run_id`
- `started_at`
- `timer_started_at`
- `prompt`
- `query`
- `collection`
- `agent_id`
- `thread_id`
- `user_id`
- `collected_vars`
- `intent`
- `raw_matches`
- `vector_matches`
- `packed_context`
- `generation`
- `final_answer`
- `tokens`
- `generator_raw`
- `nodes`
- `events`
- `tool_calls`
- `errors`
- `response`

The state should accumulate trace data as nodes run. This keeps the current workbench useful and makes graph execution inspectable.

## Nodes

The first graph should mirror the existing `RagQueryService.run()` sequence:

```text
receive_input
  -> analyze_intent
  -> retrieve_context
  -> rerank_or_fuse
  -> route_by_intent
```

`route_by_intent` branches:

```text
claim_calculation
  -> final_answer
```

or:

```text
pack_context
  -> generate_answer
  -> verify_citations
  -> final_answer
```

Node responsibilities:

- `receive_input`: trim and validate the prompt, initialize trace fields.
- `analyze_intent`: reuse the existing intent classifier and thread-state continuation behavior.
- `retrieve_context`: embed the intent query, query Chroma, serialize vector matches.
- `rerank_or_fuse`: reuse existing BM25 plus vector fusion or legacy reranking behavior.
- `route_by_intent`: branch to claim calculation when intent is `claim_calculation`.
- `claim_calculation`: reuse the existing claim calculation flow and preserve its response extras.
- `pack_context`: format cited chunks for generation.
- `generate_answer`: call the configured answer generator.
- `verify_citations`: reuse citation, number, and evidence checks.
- `final_answer`: build the current response JSON shape.

## Response Contract

The graph response must preserve the current `AgentRun` shape:

- `id`
- `mode`
- `prompt`
- `status`
- `startedAt`
- `finishedAt`
- `latencyMs`
- `nodes`
- `events`
- `toolCalls`
- `vectorMatches`
- `requestJson`
- `responseJson`
- `finalAnswer`
- `tokens` when available
- `citations`
- `retrievalDebug`
- existing calculation extras when the claim calculation branch runs

Existing frontend normalization should not need changes in this phase.

## Error Handling

FastAPI keeps its current external behavior:

- validation errors return 400
- semaphore contention returns 429
- unexpected backend errors return sanitized 500 responses

Inside the graph, node failures should append a failed node and event before raising. This lets the workbench expose where the run failed when a response can still be built in later phases. For this first phase, preserving the current route-level error behavior is acceptable if the graph cannot safely build a partial response.

## Future insurance_harness Integration

`insurance_harness` should be treated as a Python tool library, not as the API gateway. Future phases can add nodes such as:

- `load_source_registry`
- `resolve_product_identity`
- `verify_official_material`
- `query_iachina_registration`
- `score_evidence`
- `generate_research_report`

These nodes can call `insurance_harness` adapters through small interfaces. The graph shell should avoid hard-coding harness implementation details now; it only needs a clean place to attach tools later.

## Testing

Add focused tests before broad behavior changes:

- A graph smoke test that runs with fakes and returns the same top-level response fields as `RagQueryService.run()`.
- A route test showing `/agent/run_v2` uses the graph dependency and still returns nodes, events, vector matches, and final answer.
- Existing `RagQueryService` tests should keep passing.
- Existing claim calculation tests should keep passing.

The first implementation should prefer compatibility over aggressive refactoring. The main acceptance criterion is that the graph exists, route output is stable, and current tests pass.

## Acceptance Criteria

- `langgraph` is added as a backend dependency.
- `ResearchAgentGraph` can execute the existing RAG flow through LangGraph.
- `/agent/run_v2` returns the same response contract currently consumed by the workbench.
- The graph has an explicit intent branch for claim calculation.
- The implementation leaves a clear extension point for `insurance_harness` tools.
- Existing backend tests pass, with new tests covering the graph path.
