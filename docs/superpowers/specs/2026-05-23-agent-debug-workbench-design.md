# Agent Debug Workbench Design

## Goal

Build a Next.js debugging website for a FastAPI + LangGraph Agent stack. The first version should be usable before the backend is finished by running against mock data, while keeping a clean API boundary for later FastAPI integration.

## Chosen Approach

Use "Mock + API Client + Next.js Proxy".

The app will render its initial shell with Next.js SSR and then behave as an SPA for agent runs, trace exploration, node selection, JSON inspection, and mode switching. A small API layer will hide whether data comes from local mock fixtures or the FastAPI backend. Next.js route handlers will proxy browser requests to FastAPI when `NEXT_PUBLIC_AGENT_API_MODE=real`.

## Scope

### In Scope

- Next.js app using SSR for the initial workbench page.
- SPA interactions for running prompts, selecting graph nodes, inspecting traces, and switching panels.
- Mock data for LangGraph runs, node traces, state snapshots, tool calls, vector matches, and final answers.
- API client functions that can call either mock data or Next.js proxy routes.
- Next.js proxy route that forwards run requests to FastAPI.
- Workbench UI with three main regions:
  - Left rail: API mode, agent profile, vector database source, recent runs.
  - Center: prompt composer, run controls, graph node timeline, trace timeline, final answer preview.
  - Right inspector: selected node state, tool call detail, VectorDB/Qdrant matches, request and response JSON.
- Error and loading states for mock and future real backend calls.
- Basic automated checks for API shaping and UI rendering where the project tooling supports it.

### Out of Scope

- Authentication and user roles.
- Persistent run history database in the frontend project.
- Production monitoring, alerting, and billing.
- Full visual graph editor for modifying LangGraph topology.
- Direct frontend connection to Tencent Cloud VectorDB or Qdrant. Vector matches are displayed from the agent backend response.

## Architecture

The frontend is a Next.js App Router application. The main page is server-rendered, then hands control to a client workbench component for interactive debugging.

The code should separate responsibilities:

- `app/page.tsx` loads initial run data on the server and renders the workbench shell.
- `app/api/agent/run/route.ts` acts as the browser-facing proxy to FastAPI for real runs.
- `lib/api/agent-client.ts` exposes frontend-safe functions such as `createAgentRun`.
- `lib/mock/agent-runs.ts` stores deterministic mock run fixtures.
- `lib/types/agent.ts` defines shared types for runs, nodes, events, tools, vector matches, and JSON payloads.
- `components/workbench/*` contains focused UI components for the shell, prompt composer, node timeline, trace timeline, inspector, JSON viewer, and status controls.

## Data Model

An agent run contains:

- `id`: unique run identifier.
- `mode`: `mock` or `real`.
- `prompt`: the submitted user prompt.
- `status`: `idle`, `running`, `succeeded`, or `failed`.
- `startedAt` and `finishedAt`: ISO timestamps when available.
- `latencyMs`: total run latency.
- `tokens`: prompt, completion, and total token counts.
- `nodes`: ordered LangGraph nodes with status, timing, state summary, and optional error.
- `events`: trace events such as node start, node end, state update, tool call, retrieval, token stream, and final answer.
- `toolCalls`: tool name, arguments, status, duration, and result preview.
- `vectorMatches`: source, score, title, content preview, metadata, and provider label for Tencent Cloud VectorDB or Qdrant.
- `requestJson` and `responseJson`: inspectable payloads.
- `finalAnswer`: final model response.

## Backend Contract

The first real integration target is:

- Frontend route: `POST /api/agent/run`
- FastAPI route configured by `AGENT_API_BASE_URL`, expected as `POST {AGENT_API_BASE_URL}/agent/run`

Request shape:

```json
{
  "prompt": "User question",
  "agentId": "research-agent",
  "threadId": "optional-thread-id",
  "vectorProvider": "qdrant",
  "debug": true
}
```

Response shape:

```json
{
  "id": "run_001",
  "status": "succeeded",
  "prompt": "User question",
  "startedAt": "2026-05-23T06:00:00.000Z",
  "finishedAt": "2026-05-23T06:00:02.400Z",
  "latencyMs": 2400,
  "tokens": { "prompt": 820, "completion": 460, "total": 1280 },
  "nodes": [],
  "events": [],
  "toolCalls": [],
  "vectorMatches": [],
  "requestJson": {},
  "responseJson": {},
  "finalAnswer": "Answer text"
}
```

The UI should tolerate missing optional arrays by rendering empty states. The proxy should return structured errors with a message and status code if FastAPI is unavailable.

## UI Design

The visual direction should feel like a focused engineering console, not a marketing page. The first viewport should be the actual workbench.

Layout:

- A compact left rail anchors environment selection and recent runs.
- The center column is the primary operating area: prompt input, run button, node timeline, event stream, and final answer.
- The right inspector updates when a run event or node is selected.
- The interface should be responsive: desktop uses three columns, tablet collapses the right inspector below the trace, and mobile stacks controls into a single-column debug view.

Interaction:

- Running a prompt creates a new run from mock fixtures unless real API mode is selected.
- Clicking a node selects it and updates the inspector.
- Clicking a trace event highlights the related node and shows raw JSON details.
- API mode can be switched between mock and real, with real mode showing configuration errors clearly if `AGENT_API_BASE_URL` is missing.

## Error Handling

- Empty prompt: keep the run button disabled and show a subtle field hint.
- FastAPI unavailable: show a non-blocking error panel and preserve the current run.
- Malformed backend response: show an error with the raw response in the JSON panel when possible.
- Slow run: show a running status and keep controls responsive.
- Empty vector results: show an empty state instead of hiding the VectorDB panel.

## Testing Strategy

- Type checks must validate the shared agent run model.
- Unit-level checks should cover API mode selection and response normalization.
- Component rendering checks should verify that the workbench renders mock data, selected node details, vector matches, and error states.
- Manual verification should include desktop and mobile layouts, mock run creation, node selection, trace selection, and real mode configuration error behavior.

## Implementation Notes

- Start with mock mode as the default so the site works immediately.
- Keep the FastAPI contract small and explicit for the first version.
- Do not connect directly to Tencent Cloud VectorDB or Qdrant from the browser.
- Use environment variables:
  - `NEXT_PUBLIC_AGENT_API_MODE=mock|real`
  - `AGENT_API_BASE_URL=http://localhost:8000`
- Provide `.env.example` so the backend can be connected without reading source code.
