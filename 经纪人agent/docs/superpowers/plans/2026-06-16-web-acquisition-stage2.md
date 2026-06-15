# Web Acquisition Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the deterministic browser layer for the Web Acquisition Pipeline: browser context pooling and a Playwright-style fetcher that renders pages, scrolls, performs bounded safe clicks, extracts dynamic links, and returns structured partial results when browser runtime is unavailable.

**Architecture:** Stage 2 extends the existing `app/web_acquisition/` package with `BrowserPool` and `PlaywrightFetcher`. The implementation uses dependency injection and small async adapters so tests can run without a real browser while production can later wire in Playwright.

**Tech Stack:** Python 3.11+, standard library asyncio/dataclasses, existing Stage 1 `SecurityGate`, `Extractor`, `Downloader`, and pytest.

---

## Scope Note

This plan covers Stage 2 only. Browser-use, site-specific Harnesses, service orchestration, FastAPI routes, and SQLite persistence remain follow-on stages.

## File Structure

- Create `app/web_acquisition/browser_pool.py`: pooled browser/context lifecycle, cleanup, health reporting, unavailable-runtime handling.
- Create `app/web_acquisition/playwright_fetcher.py`: deterministic rendered-page fetcher, safe click filtering, extraction, quality scoring, optional PDF downloading.
- Modify `app/web_acquisition/config.py`: add browser timeouts, pool size, and click text allow/block lists.
- Create `tests/test_web_acquisition_browser_pool.py`: fake-browser tests for pooling and cleanup.
- Create `tests/test_web_acquisition_playwright_fetcher.py`: fake-page tests for security, rendered extraction, safe clicks, blocked clicks, unavailable runtime, and optional download.

## Tasks

### Task 1: BrowserPool

1. Write tests that create fake browsers and contexts, borrow contexts through an async context manager, verify context cleanup on release, verify browser reuse, and verify unavailable-runtime errors.
2. Implement `BrowserPoolUnavailable`, `BrowserLease`, and `BrowserPool`.
3. Run `pytest tests/test_web_acquisition_browser_pool.py -v`.
4. Commit with `feat: add web acquisition browser pool`.

### Task 2: PlaywrightFetcher

1. Write tests using a fake pool/page that exposes `goto`, `wait_for_load_state`, `evaluate`, `title`, `content`, `inner_text`, `candidate_elements`, and `click`.
2. Verify the fetcher validates URLs through `SecurityGate`, opens the page, waits, scrolls, extracts rendered content, clicks allowed candidates, skips blocked candidates, records click steps, and returns `strategy_used="playwright"`.
3. Verify unavailable pool errors return `AcquisitionResult(success=False)` with `playwright_unavailable`.
4. Verify optional downloader integration records downloaded PDF metadata.
5. Implement `PlaywrightFetcher` and safe/blocked click helpers.
6. Run `pytest tests/test_web_acquisition_playwright_fetcher.py -v`.
7. Commit with `feat: add deterministic playwright fetcher`.

### Task 3: Stage 2 Verification

1. Run `pytest tests/test_web_acquisition_browser_pool.py tests/test_web_acquisition_playwright_fetcher.py -v`.
2. Run all web acquisition tests with `pytest tests/test_web_acquisition_*.py -v`.
3. Run full suite with `pytest -q`.
4. Confirm `git status --short` only shows intended Stage 2 files before final commit/push.

## Self-Review

Spec coverage:

- Covers Stage 2 `BrowserPool`.
- Covers Stage 2 `PlaywrightFetcher`.
- Covers deterministic scrolling, rendered extraction, bounded safe clicks, blocked click text, step logging, unavailable-runtime fallback, and optional PDF download handoff.

Known Stage Boundaries:

- Browser-use, Harness registry, `WebAcquisitionService`, FastAPI routes, and acquisition SQLite tables are intentionally excluded.

Gap scan:

- No open-ended gaps remain for Stage 2. Tests and implementation are small enough to execute directly with TDD.
