# BOOTSTRAP

Each turn should start by assembling a complete runtime context packet.

## Injection Order

1. Current date and time.
2. Provider configuration summary.
3. Root instruction files: `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `BOOTSTRAP.md`, `MEMORY.md`, `Skills.md`, `SUB_AGENTS.md`, `PROVIDERS.md`.
4. Available tool specs.
5. Available sub-agent contracts.
6. Relevant thread memory.
7. User message.

## Current Policy

- Version 1 injects the full root context each turn.
- Later versions may switch to on-demand loading when skills or tools become too large.
- Missing root files should be reported in the context packet but should not crash the run.
