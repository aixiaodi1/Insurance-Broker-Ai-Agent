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

## Search Provider Settings

- `SEARCH_PRIMARY_PROVIDER`: Default search provider label, currently `baidu_qianfan`.
- `SEARCH_FALLBACK_PROVIDER`: Fallback search provider label, currently `firecrawl`.
- `SEARCH_HIGH_RISK_DUAL_PROVIDER`: Runs primary and fallback together for high-risk research questions.
- `SEARCH_TIMEOUT_SECONDS`: Per-provider search timeout.
- `SEARCH_MAX_RESULTS`: Default search result limit.
- `SEARCH_ENABLE_FALLBACK`: Enables fallback provider use.
- `BAIDU_QIANFAN_API_KEY`: Server-side Baidu Qianfan search key.
- `BAIDU_QIANFAN_SEARCH_ENDPOINT`: Baidu Qianfan search endpoint.
- `FIRECRAWL_API_KEY`: Server-side Firecrawl key used for Search and post-fetch Scrape recovery.
- `FIRECRAWL_SEARCH_ENDPOINT`: Firecrawl Search endpoint, defaulting to `https://api.firecrawl.dev/v2/search`.
- `FIRECRAWL_SCRAPE_ENDPOINT`: Firecrawl Scrape endpoint, defaulting to `https://api.firecrawl.dev/v2/scrape`.
- `SEARCH_TRUSTED_DOMAINS`: Optional comma-separated official-domain allowlist used for rule reranking.

## Live Search Acceptance

The five real-question workflow test runs with fake providers by default so local and CI test runs do not depend on external search accounts. To run the live provider check, configure both server-side keys and set:

```powershell
$env:BAIDU_QIANFAN_API_KEY='...'
$env:FIRECRAWL_API_KEY='...'
$env:RUN_LIVE_SEARCH_TESTS='1'
pytest tests/test_real_question_workflow.py::test_live_real_questions_search_open_and_read_sources -q
```

## Baidu Qianfan Search Modes

- Direct REST API mode uses `BAIDU_QIANFAN_SEARCH_ENDPOINT`, defaulting to `https://qianfan.baidubce.com/v2/ai_search/web_search`.
- The REST request body is chat-style JSON: `{"messages":[{"role":"user","content":"..."}]}`.
- The REST response is normalized from the provider `references` array into `web_search` results.
- MCP mode uses `https://qianfan.baidubce.com/v2/tools/web-search/mcp` through an MCP client. In MCP mode, the MCP client sends tool-call protocol messages; do not call that URL as if it were the REST search endpoint.

## Search Orchestration

- Query Planning preserves the original question while generating two to four role-specific search queries.
- Low and medium risk requests use Baidu first and call Firecrawl when safe results are insufficient.
- High-risk or fresh requests call Baidu and Firecrawl, then fuse independent provider/query rankings with RRF.
- If API results remain insufficient, a Playwright-backed public browser search is the final discovery fallback. It tries Baidu mobile search first and 360 Search when Baidu presents a browser challenge or no usable results.
- Search snippets are candidate leads only. Final citations require opening and reading source content.
- SearXNG is reserved as a future provider behind the existing `SearchProvider` protocol.

Install the optional browser fallback runtime on the backend host:

```powershell
python -m pip install -r requirements-websearch.txt
python -m playwright install chromium
```

If Playwright or Chromium is unavailable, the browser provider reports a structured failure and the search response becomes explicitly degraded.

## Safety

- Provider secrets stay server-side.
- Keys pasted into chat, logs, or issue trackers must be rotated before use.
- The frontend may show provider availability, but not API keys or raw backend diagnostics.
