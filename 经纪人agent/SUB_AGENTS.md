# SUB_AGENTS

Sub-agents are optional specialist workers. They should be invoked only when the mainline LLM chooses delegation as part of a plan.

## Available Contracts

- `evidence_searcher`: Searches insurance evidence and returns structured evidence items. This belongs to the optional insurance workflow, not the default mainline.
- `citation_verifier`: Verifies whether a claim is supported by a source URL. This belongs to verification workflows and should not be forced into every run.

## Policy

- Sub-agent results are observations, not final answers.
- A failed sub-agent should update the plan or hypothesis rather than silently producing a template response.
