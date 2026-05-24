# Agent Debug Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Next.js SSR + SPA workbench for debugging a FastAPI + LangGraph Agent with mock data first and a clean FastAPI proxy boundary.

**Architecture:** The app uses Next.js App Router for the SSR entry page and client components for the interactive workbench. Shared agent types, mock fixtures, and API helpers live under `lib/`, while `app/api/agent/run/route.ts` proxies real-mode requests to FastAPI. The UI is split into small workbench components for the left rail, prompt composer, graph timeline, trace timeline, inspector, and JSON panels.

**Tech Stack:** Next.js, React, TypeScript, Vitest, Testing Library, lucide-react, CSS modules/global CSS, FastAPI-compatible JSON over HTTP.

---

## File Structure

- Create `package.json`, `next.config.ts`, `tsconfig.json`, `vitest.config.ts`, `vitest.setup.ts`, `postcss.config.mjs`, `.env.example`.
- Create `app/layout.tsx`, `app/page.tsx`, `app/globals.css`, `app/api/agent/run/route.ts`.
- Create `lib/types/agent.ts`, `lib/mock/agent-runs.ts`, `lib/api/agent-client.ts`, `lib/api/agent-client.test.ts`, `lib/api/agent-normalize.test.ts`.
- Create `components/workbench/workbench.tsx`, `components/workbench/left-rail.tsx`, `components/workbench/prompt-composer.tsx`, `components/workbench/node-timeline.tsx`, `components/workbench/trace-timeline.tsx`, `components/workbench/inspector-panel.tsx`, `components/workbench/json-viewer.tsx`, `components/workbench/status-pill.tsx`, `components/workbench/workbench.test.tsx`.
- Create `README.md` with local run and FastAPI connection instructions.

## Task 1: Scaffold Next.js and Test Tooling

**Files:**
- Create: `package.json`
- Create: `next.config.ts`
- Create: `tsconfig.json`
- Create: `vitest.config.ts`
- Create: `vitest.setup.ts`
- Create: `postcss.config.mjs`
- Create: `.env.example`
- Create: `app/layout.tsx`
- Create: `app/page.tsx`
- Create: `app/globals.css`

- [ ] **Step 1: Create package metadata and scripts**

Create `package.json` with scripts for `dev`, `build`, `start`, `lint`, `test`, and `test:run`. Include dependencies: `@testing-library/jest-dom`, `@testing-library/react`, `@testing-library/user-event`, `@vitejs/plugin-react`, `vitest`, `jsdom`, `typescript`, `next`, `react`, `react-dom`, and `lucide-react`.

- [ ] **Step 2: Create TypeScript and test configuration**

Create `next.config.ts`, `tsconfig.json`, `vitest.config.ts`, `vitest.setup.ts`, and `postcss.config.mjs`. Vitest must use the `jsdom` environment and import `@testing-library/jest-dom/vitest` in setup.

- [ ] **Step 3: Create the initial app shell**

Create `app/layout.tsx`, `app/page.tsx`, and `app/globals.css`. `app/page.tsx` should server-render the first mock run and pass it into the client workbench component added in later tasks.

- [ ] **Step 4: Install dependencies**

Run: `npm install`

Expected: `package-lock.json` is created and dependencies install successfully.

- [ ] **Step 5: Run baseline checks**

Run: `npm run test:run`

Expected: Vitest starts successfully. It may report no tests until Task 2 adds the first test.

## Task 2: Agent Types, Mock Fixtures, and API Normalization

**Files:**
- Create: `lib/types/agent.ts`
- Create: `lib/mock/agent-runs.ts`
- Create: `lib/api/agent-client.ts`
- Create: `lib/api/agent-client.test.ts`
- Create: `lib/api/agent-normalize.test.ts`

- [ ] **Step 1: Write failing tests for response normalization**

Create tests that import `normalizeAgentRun` from `lib/api/agent-client.ts`. Verify that missing `nodes`, `events`, `toolCalls`, and `vectorMatches` become empty arrays, and that malformed response input throws an error with `Invalid agent run response`.

Run: `npm run test:run -- lib/api/agent-normalize.test.ts`

Expected: FAIL because `normalizeAgentRun` does not exist yet.

- [ ] **Step 2: Implement shared agent types**

Create `lib/types/agent.ts` with exported types for `AgentApiMode`, `AgentRunStatus`, `AgentNode`, `AgentTraceEvent`, `AgentToolCall`, `AgentVectorMatch`, `AgentRun`, `CreateAgentRunInput`, and `AgentRunError`.

- [ ] **Step 3: Implement mock fixtures and normalization**

Create `lib/mock/agent-runs.ts` with one rich deterministic run covering five nodes: `start`, `retrieve_context`, `call_tool`, `generate_answer`, and `end`. Implement `normalizeAgentRun` in `lib/api/agent-client.ts` so the tests pass.

- [ ] **Step 4: Verify normalization tests pass**

Run: `npm run test:run -- lib/api/agent-normalize.test.ts`

Expected: PASS.

- [ ] **Step 5: Write failing tests for mock API mode**

Create tests for `createAgentRun` that call it with `mode: "mock"` and expect the returned run to include the submitted prompt, `mode: "mock"`, a succeeded status, at least one node, and vector matches.

Run: `npm run test:run -- lib/api/agent-client.test.ts`

Expected: FAIL until `createAgentRun` is implemented.

- [ ] **Step 6: Implement mock API mode**

Implement `createAgentRun(input, options)` in `lib/api/agent-client.ts`. For `mode: "mock"`, return a normalized mock run with a fresh run id, the submitted prompt, current timestamps, and request/response JSON.

- [ ] **Step 7: Verify API client tests pass**

Run: `npm run test:run -- lib/api/agent-client.test.ts lib/api/agent-normalize.test.ts`

Expected: PASS.

## Task 3: FastAPI Proxy Route

**Files:**
- Create: `app/api/agent/run/route.ts`
- Modify: `lib/api/agent-client.ts`
- Modify: `.env.example`

- [ ] **Step 1: Write failing tests for real API mode request behavior**

Extend `lib/api/agent-client.test.ts` to stub `fetch`, call `createAgentRun` with `mode: "real"`, and verify it posts to `/api/agent/run` with `prompt`, `agentId`, `threadId`, `vectorProvider`, and `debug`.

Run: `npm run test:run -- lib/api/agent-client.test.ts`

Expected: FAIL until real mode is implemented.

- [ ] **Step 2: Implement real API mode in the client**

Update `createAgentRun` so `mode: "real"` posts to `/api/agent/run`, handles non-2xx responses by throwing `AgentRunError`, and normalizes successful responses.

- [ ] **Step 3: Add the Next.js proxy route**

Create `app/api/agent/run/route.ts`. It should read `AGENT_API_BASE_URL`, return a structured `503` JSON error if missing, and forward the request body to `${AGENT_API_BASE_URL}/agent/run` when configured.

- [ ] **Step 4: Update environment example**

Create `.env.example` with:

```env
NEXT_PUBLIC_AGENT_API_MODE=mock
AGENT_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 5: Verify API client tests pass**

Run: `npm run test:run -- lib/api/agent-client.test.ts`

Expected: PASS.

## Task 4: Workbench UI Components

**Files:**
- Create: `components/workbench/status-pill.tsx`
- Create: `components/workbench/json-viewer.tsx`
- Create: `components/workbench/left-rail.tsx`
- Create: `components/workbench/prompt-composer.tsx`
- Create: `components/workbench/node-timeline.tsx`
- Create: `components/workbench/trace-timeline.tsx`
- Create: `components/workbench/inspector-panel.tsx`
- Create: `components/workbench/workbench.tsx`
- Create: `components/workbench/workbench.test.tsx`
- Modify: `app/page.tsx`

- [ ] **Step 1: Write failing render tests**

Create `components/workbench/workbench.test.tsx`. Render `AgentWorkbench` with the mock run and verify it shows `LangGraph Trace Workbench`, the prompt composer, a `retrieve_context` node, vector match content, and final answer text.

Run: `npm run test:run -- components/workbench/workbench.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 2: Build presentational components**

Create `StatusPill`, `JsonViewer`, `LeftRail`, `PromptComposer`, `NodeTimeline`, `TraceTimeline`, and `InspectorPanel`. Components should receive typed props, avoid backend calls, and render deterministic content.

- [ ] **Step 3: Build the interactive workbench**

Create `AgentWorkbench` as a client component. It should manage the current run, selected node id, selected event id, prompt text, API mode, running state, and error message. It should call `createAgentRun` on submit.

- [ ] **Step 4: Wire the SSR page**

Update `app/page.tsx` to import `getInitialMockRun` from `lib/mock/agent-runs.ts` and render `AgentWorkbench`.

- [ ] **Step 5: Verify component tests pass**

Run: `npm run test:run -- components/workbench/workbench.test.tsx`

Expected: PASS.

## Task 5: Styling, Responsiveness, and Documentation

**Files:**
- Modify: `app/globals.css`
- Create: `README.md`

- [ ] **Step 1: Style the workbench**

Update `app/globals.css` with a dense engineering-console layout, three-column desktop grid, responsive tablet and mobile stacking, accessible focus states, restrained colors, and stable dimensions for node/event controls.

- [ ] **Step 2: Add project documentation**

Create `README.md` with commands for installation, development, tests, build, mock mode, and FastAPI real mode.

- [ ] **Step 3: Run full verification**

Run: `npm run test:run`

Expected: all tests pass.

Run: `npm run lint`

Expected: lint passes.

Run: `npm run build`

Expected: production build succeeds.

## Task 6: Local Server Verification

**Files:**
- No source changes expected unless verification exposes a defect.

- [ ] **Step 1: Start the development server**

Run: `npm run dev`

Expected: Next.js starts on an available local port.

- [ ] **Step 2: Verify the app manually**

Open the local URL and confirm the workbench first screen renders, prompt submission in mock mode creates a fresh run, node selection updates the inspector, and switching to real mode without FastAPI shows a clear error.

- [ ] **Step 3: Final status check**

Run: `git status --short`

Expected: only intended project files are modified or untracked.

## Self-Review

- Spec coverage: the plan covers SSR shell, SPA workbench, mock data, API client, Next.js proxy route, VectorDB/Qdrant result display, error states, responsive UI, and verification.
- Placeholder scan: no task uses open-ended placeholders; each task identifies exact files, commands, and expected outcomes.
- Type consistency: all tasks use the same core types: `AgentRun`, `AgentNode`, `AgentTraceEvent`, `AgentToolCall`, `AgentVectorMatch`, and `CreateAgentRunInput`.
