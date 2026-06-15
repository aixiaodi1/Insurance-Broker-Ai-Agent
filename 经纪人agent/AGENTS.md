# Project Rules

## Debugging Ports And Frontend Boundary

- The user debugs through port `3000` by default.
- Port `8000` is for backend/API configuration and service runtime.
- Port `3000` is user-facing by default.
- Do not expose backend-only controls, diagnostics, configuration, or implementation details in the frontend.
- Only add a frontend entry point for backend functionality when the user explicitly asks for it.

## Agent Mainline

- The default agent path is a transparent ReAct loop, not an insurance evidence workflow.
- Do not route the mainline through fixed categories such as identity, chat, clarification, or official evidence.
- The model should anchor intent openly, decompose work into falsifiable hypotheses, execute tools, observe results, and revise the plan when the user adds context.
- Public progress events should expose the execution process without exposing private model chain-of-thought.
- Insurance evidence scoring, official-source gates, RAG citation gates, and evidence-closure templates belong only in optional domain workflows.
