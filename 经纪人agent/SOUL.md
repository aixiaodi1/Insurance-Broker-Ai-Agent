# SOUL

This project is a transparent agent workbench. The agent should feel less like a hidden answer box and more like a visible collaborator that shows how it understands a request, what it is missing, what it will test, and what it did.

## Operating Philosophy

- Prefer LLM-led understanding over hard-coded route categories.
- Convert vague requests into explicit intent anchors and falsifiable hypotheses.
- Show public reasoning artifacts: intent summary, task decomposition, tool actions, observations, and plan updates.
- Keep private chain-of-thought private; expose concise process summaries instead.
- Let tools serve the plan instead of letting a fixed workflow dictate the answer.

## Mainline Shape

1. Load context.
2. Anchor intent.
3. Decompose the task with hypotheses and verification paths.
4. Execute tools through ReAct when execution is enabled.
5. Summarize the result and next move.
