# PROVIDERS

Provider settings are read from environment-backed application settings. This file documents names and purpose only; it must not contain secret values.

## LLM Provider Settings

- `LLM_PROVIDER`: Provider label used by the runtime.
- `LLM_API_BASE_URL`: Base URL for the chat-completions-compatible provider.
- `LLM_API_PATH`: API path, defaulting to `/chat/completions`.
- `LLM_MODEL`: Model name.
- `LLM_API_KEY`: Bearer token for the provider.
- `MINIMAX_API_KEY`: Fallback provider key used when configured.

## Runtime Settings

- `SUBAGENT_CONTRACTS_DIR`: Optional override for sub-agent contract files.
- `AGENT_ENABLE_WEB_SEARCH`: Enables or disables web search helpers.

## Safety

- Provider secrets stay server-side.
- The frontend may show provider availability, but not API keys or raw backend diagnostics.
