# Web Acquisition Pipeline Stage 3 Plan

## Scope

Add optional intelligent and site-specific fallback layers after deterministic HTTP and Playwright acquisition:

- Browser-use style agent adapter for hard JavaScript sites, constrained to public material discovery.
- Site-specific harness registry for insurer/product pages that need stable custom traversal.
- Shared security and action limits so these layers cannot bypass Stage 1 safeguards.

## Constraints

- Keep backend-only functionality out of the port 3000 frontend.
- Do not route the main agent path through insurance evidence scoring.
- No hard dependency on browser-use at import time; use an injected runner/adapter.
- All target URLs and discovered/downloaded URLs remain behind `SecurityGate`.
- Block login, registration, purchase, payment, consultation, captcha, and submission actions.

## Tasks

1. Browser-use fallback
   - Add config limits for max steps, navigations, clicks, and runtime.
   - Define a fixed public-material discovery prompt.
   - Implement `BrowserUseAgentFetcher` around an injected async/sync runner.
   - Normalize runner documents and actions into `AcquisitionResult`.
   - Mark blocked reported actions as failure.

2. Site-specific harnesses
   - Add `SiteSpecificHarness` protocol/base behavior.
   - Add safe domain matching registry.
   - Add `HarnessRunner` that validates the input URL before dispatch.
   - Preserve the unified `AcquisitionResult` contract.

3. Verification
   - Run new focused tests for both layers.
   - Run all web acquisition tests.
   - Run the full test suite before publishing.

## Out of Scope

- Real browser-use package installation.
- API endpoint orchestration and persistence.
- Frontend controls.
