# Web Acquisition Pipeline Design

## Context

The project is an insurance product research agent backend. The existing mainline is a transparent ReAct runtime exposed through FastAPI, and project rules keep port `3000` as the user-facing frontend while port `8000` is the backend/API boundary. The acquisition pipeline is therefore a backend service capability, not a frontend control surface and not a replacement for `/agent/research`.

The source request in `C:/Users/Administrator/新建文件夹/webfetch.md` asks for a layered, auditable pipeline for collecting public insurance company pages and documents. The system must prefer cheap deterministic collection before escalating to browser automation or intelligent browser exploration.

## Goals

Build a backend Web Acquisition Pipeline with a single service entry point:

```python
async def acquire(
    url: str,
    goal: str,
    allowed_domains: list[str] | None = None,
    strategy: str = "auto",
    max_steps: int = 20,
    timeout_seconds: int = 90,
) -> AcquisitionResult:
    ...
```

The pipeline returns a unified `AcquisitionResult` with success state, input and final URLs, strategy used, extracted text and HTML, discovered links, PDF links, downloaded files, screenshots, redirect chain, steps, errors, quality score, and duration.

The implementation must preserve these principles:

- Use ordinary HTTP first when it is sufficient.
- Escalate to Playwright only when HTTP fails or content quality is too low.
- Escalate to browser-use only when deterministic browser rules are insufficient.
- Escalate to site-specific Harness code only when intelligent exploration still fails or a known site needs fixed handling.
- Run every layer through the same `SecurityGate`.
- Never log in, register, buy, pay, submit forms, access personal centers, or bypass captchas.
- Return partial findings, steps, screenshots, and errors when a task fails.

## Scope

This design accepts the full target system but implements it in staged slices so each stage can be tested and used independently.

### Stage 1: Safe HTTP Foundation

Stage 1 creates the core backend package and implements:

- `SecurityGate`
- `Extractor`
- `FastHttpFetcher`
- `Downloader`
- shared schemas, config, and result models
- unit tests for security, extraction, HTTP quality, redirects, and downloading

This stage produces a working backend acquisition foundation without requiring Playwright or browser-use to be installed.

### Stage 2: Deterministic Browser Layer

Stage 2 implements:

- `BrowserPool`
- `PlaywrightFetcher`
- deterministic scrolling
- bounded safe clicks
- extraction from rendered pages, buttons, iframe sources, script candidates, `onclick`, `data-url`, and `data-href`
- screenshots and step logs

If Playwright is unavailable, the layer returns a structured unavailable error and the service can continue according to strategy rules.

### Stage 3: Intelligent and Site-Specific Fallbacks

Stage 3 implements:

- `BrowserUseAgentFetcher`
- a fixed browser-use instruction template for public insurance material discovery
- max step, max navigation, max click, and max runtime limits
- blocked action filtering for login, registration, purchase, payment, form submission, captcha handling, and personal center access
- `SiteSpecificHarness`
- `SiteHarnessRegistry`
- an example harness used by tests

Harnesses remain behind `SecurityGate`, rate limits, timeouts, and download limits.

### Stage 4: API, Persistence, and Integration

Stage 4 implements:

- `WebAcquisitionService`
- `POST /web-acquisition/run`
- `GET /web-acquisition/tasks/{task_id}`
- routes for task steps and downloaded files
- SQLite-backed task, step, link, file, and harness records
- integration tests through FastAPI `TestClient`

The API is backend-only. It does not add a frontend entry point unless explicitly requested later.

## Architecture

The pipeline lives under `app/web_acquisition/` with focused modules:

```text
app/web_acquisition/
  __init__.py
  schemas.py
  config.py
  security.py
  extractor.py
  quality.py
  http_fetcher.py
  downloader.py
  browser_pool.py
  playwright_fetcher.py
  browser_use_fetcher.py
  harness.py
  storage.py
  service.py
```

The package is independent from the current transparent agent runtime. The existing `app.tools.agent_tools.web_fetch` remains a lightweight research tool; it does not become the new acquisition pipeline.

## Data Flow

In `auto` strategy:

1. `WebAcquisitionService` creates a task context and starts a timeout timer.
2. `SecurityGate` validates the input URL, allowed domains, DNS results, and initial redirect rules.
3. `FastHttpFetcher` fetches with safe redirects, checks content type, extracts content, scores quality, and downloads direct PDFs.
4. If HTTP quality is sufficient, the service returns the HTTP result.
5. If HTTP quality is low, `PlaywrightFetcher` renders and extracts the page.
6. If Playwright quality is sufficient, the service returns the Playwright result.
7. If deterministic browser rules are insufficient, `BrowserUseAgentFetcher` performs bounded intelligent exploration.
8. If browser-use still fails, `SiteSpecificHarness` is selected by domain and run if available.
9. Every layer appends structured steps and errors.
10. The final result is persisted and returned.

Explicit strategies skip unrelated layers but never skip `SecurityGate`.

## Security Design

`SecurityGate` is the entry point for URL acceptance. It rejects non-HTTP schemes, localhost, loopback, private, link-local, metadata, reserved, and multicast IPs. It resolves hostnames before access and checks every resolved IP. It enforces allowed domain suffix matching so `example.com` permits `www.example.com` but rejects `example.com.evil.com`.

Redirect handling is capped at five redirects. Each redirect target is revalidated for scheme, domain, DNS, and IP class. The complete redirect chain is recorded.

Content handling allows only:

- `text/html`
- `text/plain`
- `application/json`
- `application/pdf`

Unsupported content types are rejected or marked unsupported. Downloading enforces a 50 MB single-file limit and a 200 MB per-task total download limit while streaming bytes.

## Extraction Design

`Extractor` normalizes data from HTTP, Playwright, browser-use, and Harness sources. It extracts:

- title
- text
- html
- all links
- PDF links
- document links
- iframe links
- script candidate links
- button candidate links

Link sources include `a[href]`, `iframe[src]`, `embed[src]`, `object[data]`, `button[data-url]`, `button[data-href]`, `onclick`, script text URLs, and plain text URLs. Relative links are resolved against the source page URL.

Document classification uses link text, file name, URL, and nearby context to classify insurance documents into the requested document types such as `insurance_clause`, `product_brochure`, `cash_value_table`, `rate_table`, `application_notice`, `information_disclosure`, `dividend_realization_rate`, `benefit_illustration`, and `annual_report`.

## Quality Design

Quality scoring remains deterministic and testable. The score increases when content has enough text, insurance keywords, a valid title, useful links, PDF links, and document candidates. The score decreases when the page looks like a JavaScript shell, contains loading-only content, asks to enable JavaScript, or has a high script-to-text ratio.

HTTP results below the threshold are not treated as final in `auto` mode. They are still retained as partial evidence and included in steps/errors before escalation.

## Browser Boundaries

Playwright clicks are bounded and deterministic. Allowed click text includes download, view, details, product clauses, product brochure, disclosure, expand, more, next page, PDF, rate table, cash value table, dividend realization rate, and application notice. Blocked click text includes login, registration, purchase, immediate insurance application, payment, personal center, customer service, online consultation, share, ad, appointment, submit, and captcha.

browser-use receives a fixed public-material discovery goal and must return structured findings. It is limited by max steps, max navigations, max clicks, and runtime. It must not perform blocked actions.

## Persistence Design

The acquisition storage layer uses SQLite because the project already uses SQLite for memory and tests. It creates separate acquisition tables rather than mixing with agent memory tables:

- `acquisition_tasks`
- `acquisition_steps`
- `discovered_links`
- `downloaded_files`
- `site_harnesses`

The service persists task status, final result summaries, steps, discovered document links, downloaded file metadata, SHA-256 hashes, and error messages.

## API Design

`POST /web-acquisition/run` accepts:

```json
{
  "url": "https://www.example.com/product",
  "goal": "查找这个页面中的保险产品条款、产品说明书、现金价值表、费率表、红利实现率和 PDF 下载链接",
  "allowed_domains": ["example.com"],
  "strategy": "auto",
  "max_steps": 20,
  "timeout_seconds": 90
}
```

It returns:

```json
{
  "task_id": "...",
  "status": "queued"
}
```

For the first implementation, the route may run the task synchronously behind the request while still returning a persisted task ID. A later queue worker can replace this without changing the public API.

`GET /web-acquisition/tasks/{task_id}` returns the unified result and persisted status.

## Error Handling

Errors are structured and appended rather than thrown away. Expected failures include security rejection, DNS failure, redirect rejection, unsupported content type, timeout, file too large, unavailable Playwright runtime, unavailable browser-use runtime, and missing harness.

Timeouts return partial results when available. A failure in a later layer does not erase useful output from earlier layers.

## Testing Plan

Tests are grouped by layer:

- security tests for forbidden schemes, localhost, private ranges, metadata IPs, allowed domains, and redirect safety
- extractor tests for title, text, absolute links, PDF links, button links, iframe links, script candidates, and document classification
- HTTP tests for ordinary HTML, empty JavaScript shell detection, content type handling, redirect recording, and quality escalation
- downloader tests for PDF save, SHA-256 calculation, deduplication, streaming size limit, total task limit, and rejected content types
- Playwright tests with optional runtime guards and deterministic fake adapters where browser runtime is unavailable
- browser-use tests with fake adapters to prove goal construction, max step enforcement, blocked action filtering, structured output, and fallback
- Harness tests for registry lookup and unified output
- service and API tests for strategy routing, task persistence, and result shape

## Non-Goals

The pipeline does not provide consumer-facing insurance advice. It does not recommend products, promise returns, or produce sales language. It does not bypass authentication, captchas, or anti-abuse controls. It does not expose backend-only diagnostics or controls in the frontend.

## Rollout

Implementation follows the staged design:

1. Safe HTTP Foundation
2. Deterministic Browser Layer
3. Intelligent and Site-Specific Fallbacks
4. API, Persistence, and Integration

Each stage must have passing tests before the next stage starts.
