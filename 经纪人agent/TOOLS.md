# TOOLS

This file lists tool capabilities available to the agent mainline. The runtime should inject this list each turn so the LLM can choose tools through ReAct.

## Read And Search Tools

- `local_search`: Search text files under the configured local source root.
- `local_read`: Read supported local text files with a character limit.
- `web_search`: Search the public web for candidate pages.
- `web_fetch`: Fetch a public URL and extract plain text.

## Domain And Data Tools

- `search_local_specs`: Search curated local insurance product specs by company or product name. This is a domain workflow helper, not a mainline gate.
- `resolve_product_alias`: Resolve a product name and aliases into a canonical identity candidate.
- `rag_search`: Placeholder RAG search. It currently returns no formal citations until a corpus is configured.

## Command Tool

- `run_cli`: Execute a small allowlist of read-oriented commands such as `rg`, `dir`, `ls`, and `Get-ChildItem`.
- `run_cli` must not be exposed as a default autonomous action for ordinary research. Use it only for explicit command requests or approved execution modes.

## Tool Use Policy

- Tool call JSON is an internal action, not a final answer.
- Tool results are observations that must be fed back to the LLM before it decides the next step.
- Tool failures should update the hypothesis or plan instead of ending the run unless the failure is unrecoverable.
