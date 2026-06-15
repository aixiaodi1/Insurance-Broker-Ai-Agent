# Skills

Skills are reusable capability descriptions that the agent can load or apply during task execution.

## Current Project Skills

- Transparent ReAct mainline: understand intent, decompose into hypotheses, execute tools, observe, and revise.
- Context compaction: summarize long messages and tool events when the context budget is exceeded.
- Hermes-style memory: store user, project, evidence, and thread memory in SQLite and root markdown files.
- Insurance research workflow: optional domain workflow for product research. It is not the mainline.

## Loading Policy

- Version 1 injects this skills list every turn.
- Future versions may load detailed skill instructions on demand.
