# Web Acquisition Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the safe HTTP foundation for the Web Acquisition Pipeline: shared schemas, security validation, extraction, deterministic quality scoring, ordinary HTTP fetching, and safe PDF downloading.

**Architecture:** Stage 1 creates an isolated backend package under `app/web_acquisition/` and leaves the current transparent ReAct agent runtime unchanged. The package uses focused modules with injectable network functions so security, redirects, extraction, and downloads can be tested without live network access.

**Tech Stack:** Python 3.11+, standard library dataclasses/networking/parsing, pytest, FastAPI project conventions.

---

## Scope Note

This plan covers Stage 1 from `docs/superpowers/specs/2026-06-15-web-acquisition-pipeline-design.md`. BrowserPool, PlaywrightFetcher, BrowserUseAgentFetcher, SiteSpecificHarness, API routes, and SQLite persistence are separate stages because they are independent subsystems and should each produce testable software on their own.

## File Structure

- Create `app/web_acquisition/__init__.py`: package exports.
- Create `app/web_acquisition/config.py`: size limits, timeouts, content type allowlist, and quality threshold.
- Create `app/web_acquisition/schemas.py`: result, link, file, step, error, and fetch response models.
- Create `app/web_acquisition/security.py`: URL, DNS, IP range, allowed domain, and redirect validation.
- Create `app/web_acquisition/extractor.py`: HTML/text extraction, link discovery, PDF detection, document classification.
- Create `app/web_acquisition/quality.py`: deterministic quality score and escalation reasons.
- Create `app/web_acquisition/http_fetcher.py`: safe ordinary HTTP fetcher with injected transport.
- Create `app/web_acquisition/downloader.py`: streaming downloader with safety checks, SHA-256, and deduplication.
- Create `tests/test_web_acquisition_security.py`: security and redirect tests.
- Create `tests/test_web_acquisition_extractor.py`: extraction and classification tests.
- Create `tests/test_web_acquisition_quality.py`: quality scoring tests.
- Create `tests/test_web_acquisition_http_fetcher.py`: HTTP fetch behavior tests.
- Create `tests/test_web_acquisition_downloader.py`: PDF download, hash, dedupe, and size tests.

## Task 1: Package Config and Schemas

**Files:**
- Create: `app/web_acquisition/__init__.py`
- Create: `app/web_acquisition/config.py`
- Create: `app/web_acquisition/schemas.py`
- Test: `tests/test_web_acquisition_quality.py`

- [ ] **Step 1: Write the failing schema/config smoke test**

Add this to `tests/test_web_acquisition_quality.py`:

```python
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep


def test_stage1_defaults_and_result_shape():
    config = WebAcquisitionConfig()
    step = AcquisitionStep(layer="security", action="validate", description="validated input URL")
    result = AcquisitionResult(
        success=True,
        input_url="https://example.com/product",
        final_url="https://example.com/product",
        strategy_used="http",
        title="Example",
        steps=[step],
        quality_score=0.8,
    )

    assert config.max_redirects == 5
    assert config.max_file_size_bytes == 50 * 1024 * 1024
    assert config.max_total_download_bytes == 200 * 1024 * 1024
    assert "application/pdf" in config.allowed_content_types
    assert result.steps[0].layer == "security"
    assert result.errors == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_web_acquisition_quality.py::test_stage1_defaults_and_result_shape -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition'`.

- [ ] **Step 3: Create package exports**

Create `app/web_acquisition/__init__.py`:

```python
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.schemas import AcquisitionResult

__all__ = ["AcquisitionResult", "WebAcquisitionConfig"]
```

- [ ] **Step 4: Create config defaults**

Create `app/web_acquisition/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WebAcquisitionConfig:
    request_timeout_seconds: int = 10
    total_timeout_seconds: int = 90
    download_timeout_seconds: int = 30
    max_redirects: int = 5
    max_file_size_bytes: int = 50 * 1024 * 1024
    max_total_download_bytes: int = 200 * 1024 * 1024
    quality_success_threshold: float = 0.65
    downloads_dir: Path = Path("data/downloads")
    allowed_content_types: set[str] = field(
        default_factory=lambda: {
            "text/html",
            "text/plain",
            "application/json",
            "application/pdf",
        }
    )
```

- [ ] **Step 5: Create shared schemas**

Create `app/web_acquisition/schemas.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StrategyName = Literal["auto", "http_only", "playwright_only", "browser_use_only", "harness_only"]
StrategyUsed = Literal["http", "playwright", "browser_use", "harness", "none"]


@dataclass(slots=True)
class AcquisitionStep:
    layer: str
    action: str
    description: str
    url_before: str | None = None
    url_after: str | None = None
    screenshot_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AcquisitionError:
    code: str
    message: str
    layer: str
    url: str | None = None


@dataclass(slots=True)
class DiscoveredLink:
    url: str
    text: str = ""
    document_type: str = "unknown"
    confidence: float = 0.0
    source: str = "unknown"
    source_page: str = ""


@dataclass(slots=True)
class DownloadedFile:
    source_url: str
    final_url: str
    file_path: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


@dataclass(slots=True)
class ExtractedContent:
    title: str = ""
    text: str = ""
    html: str = ""
    links: list[DiscoveredLink] = field(default_factory=list)
    pdf_links: list[DiscoveredLink] = field(default_factory=list)
    document_links: list[DiscoveredLink] = field(default_factory=list)
    iframe_links: list[DiscoveredLink] = field(default_factory=list)
    script_candidate_links: list[DiscoveredLink] = field(default_factory=list)
    button_candidate_links: list[DiscoveredLink] = field(default_factory=list)


@dataclass(slots=True)
class FetchResponse:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        raw = self.headers.get("content-type") or self.headers.get("Content-Type") or ""
        return raw.split(";", 1)[0].strip().lower()


@dataclass(slots=True)
class AcquisitionResult:
    success: bool
    input_url: str
    final_url: str = ""
    strategy_used: StrategyUsed = "none"
    title: str = ""
    text: str = ""
    html: str = ""
    links: list[DiscoveredLink] = field(default_factory=list)
    pdf_links: list[DiscoveredLink] = field(default_factory=list)
    downloaded_files: list[DownloadedFile] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    redirect_chain: list[str] = field(default_factory=list)
    steps: list[AcquisitionStep] = field(default_factory=list)
    errors: list[AcquisitionError] = field(default_factory=list)
    quality_score: float = 0.0
    duration_ms: int = 0
```

- [ ] **Step 6: Run the smoke test**

Run: `pytest tests/test_web_acquisition_quality.py::test_stage1_defaults_and_result_shape -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/web_acquisition/__init__.py app/web_acquisition/config.py app/web_acquisition/schemas.py tests/test_web_acquisition_quality.py
git commit -m "feat: add web acquisition stage1 schemas"
```

## Task 2: SecurityGate URL, DNS, Domains, and Redirects

**Files:**
- Create: `app/web_acquisition/security.py`
- Test: `tests/test_web_acquisition_security.py`

- [ ] **Step 1: Write failing security tests**

Create `tests/test_web_acquisition_security.py`:

```python
import pytest

from app.web_acquisition.security import SecurityGate, SecurityViolation


def resolver_for(ip: str):
    return lambda host: [ip]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "ftp://example.com/file",
        "chrome://version",
    ],
)
def test_security_gate_rejects_forbidden_schemes(url):
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url(url)

    assert exc.value.code == "scheme_not_allowed"


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://localhost", "127.0.0.1"),
        ("http://127.0.0.1", "127.0.0.1"),
        ("http://0.0.0.0", "0.0.0.0"),
        ("http://10.1.2.3", "10.1.2.3"),
        ("http://172.16.0.1", "172.16.0.1"),
        ("http://192.168.1.20", "192.168.1.20"),
        ("http://169.254.169.254", "169.254.169.254"),
        ("http://example.com", "224.0.0.1"),
    ],
)
def test_security_gate_rejects_unsafe_hosts_and_resolved_ips(url, ip):
    gate = SecurityGate(resolve_host=resolver_for(ip))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url(url)

    assert exc.value.code in {"host_not_allowed", "ip_not_allowed"}


def test_security_gate_allows_allowed_domain_and_subdomain():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    assert gate.validate_url("https://www.example.com/a", allowed_domains=["example.com"]).normalized_url == "https://www.example.com/a"


def test_security_gate_rejects_domain_suffix_spoofing():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url("https://example.com.evil.com", allowed_domains=["example.com"])

    assert exc.value.code == "domain_not_allowed"


def test_security_gate_revalidates_redirect_chain():
    gate = SecurityGate(resolve_host=lambda host: ["93.184.216.34"] if host == "example.com" else ["10.0.0.2"])

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_redirect_chain(
            "https://example.com/start",
            ["https://example.com/step", "https://internal.example.test/private"],
            allowed_domains=["example.com"],
        )

    assert exc.value.code in {"domain_not_allowed", "ip_not_allowed"}


def test_security_gate_rejects_too_many_redirects():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"), max_redirects=2)

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_redirect_chain(
            "https://example.com/start",
            ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            allowed_domains=["example.com"],
        )

    assert exc.value.code == "too_many_redirects"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_acquisition_security.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition.security'`.

- [ ] **Step 3: Implement SecurityGate**

Create `app/web_acquisition/security.py`:

```python
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254")}


class SecurityViolation(ValueError):
    def __init__(self, code: str, message: str, url: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.url = url


@dataclass(slots=True)
class SecurityCheckResult:
    normalized_url: str
    host: str
    resolved_ips: list[str]


class SecurityGate:
    def __init__(self, resolve_host=None, max_redirects: int = 5) -> None:
        self._resolve_host = resolve_host or self._default_resolve_host
        self.max_redirects = max_redirects

    def validate_url(self, url: str, allowed_domains: list[str] | None = None) -> SecurityCheckResult:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise SecurityViolation("scheme_not_allowed", f"URL scheme is not allowed: {parsed.scheme}", url)
        if not parsed.hostname:
            raise SecurityViolation("host_required", "URL host is required", url)

        host = parsed.hostname.lower().strip(".")
        if host in BLOCKED_HOSTS:
            raise SecurityViolation("host_not_allowed", f"Host is not allowed: {host}", url)
        if allowed_domains and not self._domain_allowed(host, allowed_domains):
            raise SecurityViolation("domain_not_allowed", f"Host is outside allowed domains: {host}", url)

        resolved_ips = self._resolve_or_parse_ip(host)
        for ip_text in resolved_ips:
            self._validate_ip(ip_text, url)

        normalized = urlunparse(parsed._replace(fragment=""))
        return SecurityCheckResult(normalized_url=normalized, host=host, resolved_ips=resolved_ips)

    def validate_redirect_chain(
        self,
        initial_url: str,
        redirect_chain: list[str],
        allowed_domains: list[str] | None = None,
    ) -> list[SecurityCheckResult]:
        if len(redirect_chain) > self.max_redirects:
            raise SecurityViolation("too_many_redirects", "Redirect chain exceeds maximum redirects", initial_url)
        results = [self.validate_url(initial_url, allowed_domains=allowed_domains)]
        for target in redirect_chain:
            results.append(self.validate_url(target, allowed_domains=allowed_domains))
        return results

    def _resolve_or_parse_ip(self, host: str) -> list[str]:
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            return self._resolve_host(host)

    def _validate_ip(self, ip_text: str, url: str) -> None:
        ip = ipaddress.ip_address(ip_text)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip in METADATA_IPS
        ):
            raise SecurityViolation("ip_not_allowed", f"Resolved IP is not allowed: {ip}", url)

    def _domain_allowed(self, host: str, allowed_domains: list[str]) -> bool:
        normalized = [domain.lower().strip(".") for domain in allowed_domains]
        return any(host == domain or host.endswith(f".{domain}") for domain in normalized)

    def _default_resolve_host(self, host: str) -> list[str]:
        infos = socket.getaddrinfo(host, None)
        return sorted({info[4][0] for info in infos})
```

- [ ] **Step 4: Run security tests**

Run: `pytest tests/test_web_acquisition_security.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web_acquisition/security.py tests/test_web_acquisition_security.py
git commit -m "feat: add web acquisition security gate"
```

## Task 3: Extractor and Document Classification

**Files:**
- Create: `app/web_acquisition/extractor.py`
- Test: `tests/test_web_acquisition_extractor.py`

- [ ] **Step 1: Write failing extractor tests**

Create `tests/test_web_acquisition_extractor.py`:

```python
from app.web_acquisition.extractor import Extractor, classify_document


def test_extractor_finds_title_text_links_and_pdf_candidates():
    html = """
    <html>
      <head><title>官方产品资料</title></head>
      <body>
        <h1>保险产品信息披露</h1>
        <a href="/docs/clause.pdf">产品条款 PDF</a>
        <a href="https://static.example.com/rate.pdf">费率表</a>
        <iframe src="/frame/disclosure.html"></iframe>
        <button data-url="/download/cash-value.pdf">现金价值表下载</button>
        <button onclick="window.open('/notice/application.pdf')">投保须知</button>
        <script>var u = "https://example.com/files/dividend.pdf";</script>
      </body>
    </html>
    """

    extracted = Extractor().extract_html(html, "https://example.com/product/index.html")

    assert extracted.title == "官方产品资料"
    assert "保险产品信息披露" in extracted.text
    assert {item.url for item in extracted.pdf_links} >= {
        "https://example.com/docs/clause.pdf",
        "https://static.example.com/rate.pdf",
        "https://example.com/download/cash-value.pdf",
        "https://example.com/notice/application.pdf",
        "https://example.com/files/dividend.pdf",
    }
    assert extracted.iframe_links[0].url == "https://example.com/frame/disclosure.html"
    assert any(item.document_type == "cash_value_table" for item in extracted.document_links)


def test_classify_document_uses_chinese_text_and_url():
    clause = classify_document("产品条款", "https://example.com/a.pdf")
    rate = classify_document("", "https://example.com/files/rate-table.pdf")
    unknown = classify_document("下载", "https://example.com/file.bin")

    assert clause.document_type == "insurance_clause"
    assert clause.confidence >= 0.8
    assert rate.document_type == "rate_table"
    assert unknown.document_type == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_acquisition_extractor.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition.extractor'`.

- [ ] **Step 3: Implement Extractor**

Create `app/web_acquisition/extractor.py`:

```python
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from app.web_acquisition.schemas import DiscoveredLink, ExtractedContent


URL_RE = re.compile(r"https?://[^\s'\"<>）)]+|/[A-Za-z0-9_./?=&%+-]+")
SCRIPT_URL_RE = re.compile(r"https?://[^\s'\"<>）)]+|/[A-Za-z0-9_./?=&%+-]+\.(?:pdf|html?|json)", re.I)

DOCUMENT_PATTERNS: list[tuple[str, tuple[str, ...], float]] = [
    ("insurance_clause", ("产品条款", "保险条款", "条款", "clause"), 0.9),
    ("product_brochure", ("产品说明书", "说明书", "brochure"), 0.88),
    ("cash_value_table", ("现金价值", "cash-value", "cash_value"), 0.9),
    ("rate_table", ("费率", "rate-table", "rate_table", "rate"), 0.86),
    ("application_notice", ("投保须知", "application"), 0.86),
    ("health_disclosure", ("健康告知", "health"), 0.84),
    ("claim_notice", ("理赔须知", "claim"), 0.82),
    ("information_disclosure", ("信息披露", "disclosure"), 0.84),
    ("dividend_realization_rate", ("红利实现率", "分红实现率", "dividend"), 0.9),
    ("benefit_illustration", ("利益演示", "benefit"), 0.82),
    ("annual_report", ("年度报告", "annual-report", "annual_report"), 0.8),
]


class Extractor:
    def extract_html(self, html_text: str, base_url: str) -> ExtractedContent:
        parser = _HTMLCollector()
        parser.feed(html_text)

        links = [self._link(urljoin(base_url, href), text, "a[href]", base_url) for href, text in parser.links]
        iframe_links = [self._link(urljoin(base_url, src), "", "iframe[src]", base_url) for src in parser.iframe_sources]
        button_links = [
            self._link(urljoin(base_url, target), text, "button", base_url)
            for target, text in parser.button_targets
        ]
        script_links = [
            self._link(urljoin(base_url, target), "", "script", base_url)
            for target in self._unique(self._script_candidates(parser.script_text))
        ]
        plain_links = [
            self._link(urljoin(base_url, target), "", "plain_text", base_url)
            for target in self._unique(URL_RE.findall(parser.visible_text()))
        ]

        all_links = self._dedupe(links + iframe_links + button_links + script_links + plain_links)
        pdf_links = [item for item in all_links if self._looks_pdf(item.url)]
        document_links = [item for item in all_links if item.document_type != "unknown" or self._looks_pdf(item.url)]

        return ExtractedContent(
            title=parser.title.strip(),
            text=parser.visible_text(),
            html=html_text,
            links=all_links,
            pdf_links=pdf_links,
            document_links=document_links,
            iframe_links=iframe_links,
            script_candidate_links=script_links,
            button_candidate_links=button_links,
        )

    def extract_text(self, text: str, base_url: str) -> ExtractedContent:
        links = [self._link(urljoin(base_url, target), "", "plain_text", base_url) for target in self._unique(URL_RE.findall(text))]
        return ExtractedContent(
            text=re.sub(r"\s+", " ", text).strip(),
            links=links,
            pdf_links=[item for item in links if self._looks_pdf(item.url)],
            document_links=[item for item in links if item.document_type != "unknown" or self._looks_pdf(item.url)],
        )

    def _link(self, url: str, text: str, source: str, source_page: str) -> DiscoveredLink:
        classification = classify_document(text, url)
        return DiscoveredLink(
            url=url,
            text=re.sub(r"\s+", " ", html.unescape(text)).strip(),
            document_type=classification.document_type,
            confidence=classification.confidence,
            source=source,
            source_page=source_page,
        )

    def _script_candidates(self, script_text: str) -> list[str]:
        return SCRIPT_URL_RE.findall(script_text)

    def _looks_pdf(self, url: str) -> bool:
        return ".pdf" in url.lower().split("?", 1)[0]

    def _dedupe(self, links: list[DiscoveredLink]) -> list[DiscoveredLink]:
        seen: set[str] = set()
        deduped: list[DiscoveredLink] = []
        for link in links:
            if link.url in seen:
                continue
            seen.add(link.url)
            deduped.append(link)
        return deduped

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


def classify_document(text: str, url: str) -> DiscoveredLink:
    haystack = f"{text} {url}".lower()
    for document_type, needles, confidence in DOCUMENT_PATTERNS:
        if any(needle.lower() in haystack for needle in needles):
            return DiscoveredLink(url=url, text=text, document_type=document_type, confidence=confidence)
    return DiscoveredLink(url=url, text=text, document_type="unknown", confidence=0.0)


class _HTMLCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.links: list[tuple[str, str]] = []
        self.iframe_sources: list[str] = []
        self.button_targets: list[tuple[str, str]] = []
        self.script_text = ""
        self._text_parts: list[str] = []
        self._current_link: str | None = None
        self._current_link_text: list[str] = []
        self._current_button_target: str | None = None
        self._current_button_text: list[str] = []
        self._in_title = False
        self._in_script = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag in {"style", "noscript", "svg", "nav", "header", "footer"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "script":
            self._in_script = True
        if tag == "a" and attrs_dict.get("href"):
            self._current_link = attrs_dict["href"]
            self._current_link_text = []
        if tag == "iframe" and attrs_dict.get("src"):
            self.iframe_sources.append(attrs_dict["src"])
        if tag in {"button", "a"}:
            target = attrs_dict.get("data-url") or attrs_dict.get("data-href") or self._target_from_onclick(attrs_dict.get("onclick", ""))
            if target:
                self._current_button_target = target
                self._current_button_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "noscript", "svg", "nav", "header", "footer"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_script = False
        if tag == "a" and self._current_link:
            self.links.append((self._current_link, " ".join(self._current_link_text)))
            self._current_link = None
        if tag in {"button", "a"} and self._current_button_target:
            self.button_targets.append((self._current_button_target, " ".join(self._current_button_text)))
            self._current_button_target = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_script:
            self.script_text += "\n" + data
            return
        if self._skip_depth:
            return
        if self._current_link is not None:
            self._current_link_text.append(data.strip())
        if self._current_button_target is not None:
            self._current_button_text.append(data.strip())
        if data.strip():
            self._text_parts.append(data.strip())

    def visible_text(self) -> str:
        return re.sub(r"\s+", " ", html.unescape(" ".join(self._text_parts))).strip()

    def _target_from_onclick(self, onclick: str) -> str:
        match = re.search(r"['\"]([^'\"]+\.(?:pdf|html?|json)[^'\"]*)['\"]", onclick, re.I)
        return match.group(1) if match else ""
```

- [ ] **Step 4: Run extractor tests**

Run: `pytest tests/test_web_acquisition_extractor.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web_acquisition/extractor.py tests/test_web_acquisition_extractor.py
git commit -m "feat: add web acquisition extractor"
```

## Task 4: Quality Scoring

**Files:**
- Create: `app/web_acquisition/quality.py`
- Modify: `tests/test_web_acquisition_quality.py`

- [ ] **Step 1: Add failing quality tests**

Append to `tests/test_web_acquisition_quality.py`:

```python
from app.web_acquisition.extractor import Extractor
from app.web_acquisition.quality import score_quality


def test_quality_score_rewards_insurance_content_and_pdf_links():
    html = """
    <html><head><title>保险产品信息披露</title></head><body>
    <p>保险 产品 条款 费率 现金价值 产品说明书 投保须知 信息披露 分红 红利实现率 年金 终身寿 医疗险 重疾险</p>
    <p>""" + ("保险责任 " * 80) + """</p>
    <a href="/clause.pdf">产品条款</a>
    </body></html>
    """
    extracted = Extractor().extract_html(html, "https://example.com/product")

    assessment = score_quality(extracted)

    assert assessment.score >= 0.65
    assert assessment.should_escalate is False


def test_quality_score_escalates_javascript_shell():
    html = """
    <html><head><title>Loading</title></head><body>
      <div id="app-root"></div>
      <script>window.__NEXT_DATA__ = {"props": {}};</script>
      <script src="/bundle.js"></script>
    </body></html>
    """
    extracted = Extractor().extract_html(html, "https://example.com/product")

    assessment = score_quality(extracted)

    assert assessment.score < 0.65
    assert assessment.should_escalate is True
    assert "js_shell" in assessment.reasons
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_acquisition_quality.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition.quality'`.

- [ ] **Step 3: Implement quality scorer**

Create `app/web_acquisition/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from app.web_acquisition.schemas import ExtractedContent


INSURANCE_KEYWORDS = (
    "保险",
    "产品",
    "条款",
    "费率",
    "现金价值",
    "产品说明书",
    "投保须知",
    "保险责任",
    "信息披露",
    "分红",
    "红利实现率",
    "年金",
    "终身寿",
    "医疗险",
    "重疾险",
)

JS_SHELL_MARKERS = ("请开启javascript", "请启用javascript", "loading", "app-root", "__next_data__", "id=\"app\"", "id='app'")


@dataclass(slots=True)
class QualityAssessment:
    score: float
    should_escalate: bool
    reasons: list[str]


def score_quality(extracted: ExtractedContent, threshold: float = 0.65) -> QualityAssessment:
    score = 0.0
    reasons: list[str] = []
    text = extracted.text or ""
    html = extracted.html or ""
    lowered = f"{text} {html}".lower()

    if len(text) >= 500:
        score += 0.25
    else:
        reasons.append("short_text")

    keyword_hits = sum(1 for keyword in INSURANCE_KEYWORDS if keyword in text)
    if keyword_hits:
        score += min(0.25, keyword_hits * 0.03)
    else:
        reasons.append("missing_insurance_keywords")

    if extracted.title and extracted.title.lower() not in {"loading", "undefined"}:
        score += 0.1
    else:
        reasons.append("weak_title")

    if extracted.links:
        score += 0.1
    else:
        reasons.append("missing_links")

    if extracted.pdf_links:
        score += 0.15
    if extracted.document_links:
        score += 0.15

    if any(marker in lowered for marker in JS_SHELL_MARKERS):
        score -= 0.25
        reasons.append("js_shell")

    if html.lower().count("<script") >= 3 and len(text) < 500:
        score -= 0.15
        reasons.append("script_heavy")

    normalized = max(0.0, min(1.0, round(score, 3)))
    return QualityAssessment(score=normalized, should_escalate=normalized < threshold, reasons=reasons)
```

- [ ] **Step 4: Run quality tests**

Run: `pytest tests/test_web_acquisition_quality.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web_acquisition/quality.py tests/test_web_acquisition_quality.py
git commit -m "feat: add web acquisition quality scoring"
```

## Task 5: FastHttpFetcher

**Files:**
- Create: `app/web_acquisition/http_fetcher.py`
- Test: `tests/test_web_acquisition_http_fetcher.py`

- [ ] **Step 1: Write failing HTTP fetcher tests**

Create `tests/test_web_acquisition_http_fetcher.py`:

```python
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.http_fetcher import FastHttpFetcher
from app.web_acquisition.schemas import FetchResponse
from app.web_acquisition.security import SecurityGate


def test_fast_http_fetcher_extracts_good_html_without_escalation():
    html = """
    <html><head><title>保险产品信息披露</title></head><body>
    <p>""" + ("保险 产品 条款 费率 现金价值 产品说明书 信息披露 " * 50) + """</p>
    <a href="/clause.pdf">产品条款</a>
    </body></html>
    """.encode("utf-8")

    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(
            url=url,
            final_url="https://example.com/product",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html,
            redirect_chain=["https://example.com/product"],
        )

    fetcher = FastHttpFetcher(
        config=WebAcquisitionConfig(),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = fetcher.fetch("https://example.com/product", goal="find docs", allowed_domains=["example.com"])

    assert result.success is True
    assert result.strategy_used == "http"
    assert result.title == "保险产品信息披露"
    assert result.quality_score >= 0.65
    assert result.errors == []
    assert result.pdf_links[0].url == "https://example.com/clause.pdf"


def test_fast_http_fetcher_marks_low_quality_html_for_escalation():
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "text/html"},
            body=b"<html><body><div id='app-root'></div><script src='/app.js'></script></body></html>",
        )

    fetcher = FastHttpFetcher(
        config=WebAcquisitionConfig(),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = fetcher.fetch("https://example.com/app", goal="find docs", allowed_domains=["example.com"])

    assert result.success is False
    assert result.strategy_used == "http"
    assert result.quality_score < 0.65
    assert result.errors[0].code == "quality_too_low"


def test_fast_http_fetcher_rejects_unsupported_content_type():
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "image/png"},
            body=b"png",
        )

    fetcher = FastHttpFetcher(
        config=WebAcquisitionConfig(),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = fetcher.fetch("https://example.com/image.png", goal="find docs", allowed_domains=["example.com"])

    assert result.success is False
    assert result.errors[0].code == "unsupported_content_type"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_acquisition_http_fetcher.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition.http_fetcher'`.

- [ ] **Step 3: Implement FastHttpFetcher**

Create `app/web_acquisition/http_fetcher.py`:

```python
from __future__ import annotations

from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.extractor import Extractor
from app.web_acquisition.quality import score_quality
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep, FetchResponse
from app.web_acquisition.security import SecurityGate, SecurityViolation


class FastHttpFetcher:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        transport=None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.transport = transport or self._default_transport
        self.extractor = Extractor()

    def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="security", action="validate", description="Validate input URL", url_before=url)]
        try:
            self.security_gate.validate_url(url, allowed_domains=allowed_domains)
            response = self.transport(url, self.config.request_timeout_seconds, self.config.max_redirects)
            self.security_gate.validate_redirect_chain(url, response.redirect_chain, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return self._failure(url, "security", exc.code, str(exc), started, steps)
        except Exception as exc:
            return self._failure(url, "http", type(exc).__name__, str(exc), started, steps)

        content_type = response.content_type
        if content_type not in self.config.allowed_content_types:
            return self._failure(url, "http", "unsupported_content_type", content_type, started, steps, final_url=response.final_url)

        steps.append(
            AcquisitionStep(
                layer="http",
                action="fetch",
                description=f"Fetched {response.final_url} with status {response.status_code}",
                url_before=url,
                url_after=response.final_url,
                metadata={"content_type": content_type},
            )
        )

        if content_type == "application/pdf":
            return AcquisitionResult(
                success=True,
                input_url=url,
                final_url=response.final_url,
                strategy_used="http",
                redirect_chain=response.redirect_chain,
                steps=steps,
                quality_score=1.0,
                duration_ms=self._duration(started),
            )

        text = response.body.decode("utf-8", errors="ignore")
        extracted = self.extractor.extract_html(text, response.final_url) if content_type == "text/html" else self.extractor.extract_text(text, response.final_url)
        quality = score_quality(extracted, threshold=self.config.quality_success_threshold)
        errors = []
        if quality.should_escalate:
            errors.append(
                AcquisitionError(
                    code="quality_too_low",
                    message="HTTP content quality is below threshold",
                    layer="http",
                    url=response.final_url,
                )
            )

        return AcquisitionResult(
            success=not quality.should_escalate,
            input_url=url,
            final_url=response.final_url,
            strategy_used="http",
            title=extracted.title,
            text=extracted.text,
            html=extracted.html,
            links=extracted.links,
            pdf_links=extracted.pdf_links,
            redirect_chain=response.redirect_chain,
            steps=steps,
            errors=errors,
            quality_score=quality.score,
            duration_ms=self._duration(started),
        )

    def _failure(
        self,
        input_url: str,
        layer: str,
        code: str,
        message: str,
        started: float,
        steps: list[AcquisitionStep],
        final_url: str = "",
    ) -> AcquisitionResult:
        return AcquisitionResult(
            success=False,
            input_url=input_url,
            final_url=final_url,
            strategy_used="http",
            steps=steps,
            errors=[AcquisitionError(code=code, message=message, layer=layer, url=input_url)],
            duration_ms=self._duration(started),
        )

    def _default_transport(self, url: str, timeout_seconds: int, max_redirects: int) -> FetchResponse:
        opener = build_opener()
        request = Request(url, headers={"User-Agent": "insurance-web-acquisition/0.1"})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read()
                final_url = response.geturl()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return FetchResponse(
                    url=url,
                    final_url=final_url,
                    status_code=response.status,
                    headers=headers,
                    body=body,
                    redirect_chain=[final_url] if final_url != url else [],
                )
        except HTTPError as exc:
            body = exc.read()
            headers = {key.lower(): value for key, value in exc.headers.items()}
            return FetchResponse(url=url, final_url=exc.url, status_code=exc.code, headers=headers, body=body)
        except URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    def _duration(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
```

- [ ] **Step 4: Run HTTP fetcher tests**

Run: `pytest tests/test_web_acquisition_http_fetcher.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web_acquisition/http_fetcher.py tests/test_web_acquisition_http_fetcher.py
git commit -m "feat: add web acquisition HTTP fetcher"
```

## Task 6: Downloader

**Files:**
- Create: `app/web_acquisition/downloader.py`
- Test: `tests/test_web_acquisition_downloader.py`

- [ ] **Step 1: Write failing downloader tests**

Create `tests/test_web_acquisition_downloader.py`:

```python
import hashlib

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.downloader import Downloader
from app.web_acquisition.schemas import FetchResponse
from app.web_acquisition.security import SecurityGate


def test_downloader_saves_pdf_by_sha256_and_deduplicates(tmp_path):
    body = b"%PDF-1.4\nsample"
    expected_sha = hashlib.sha256(body).hexdigest()

    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=body,
        )

    config = WebAcquisitionConfig(downloads_dir=tmp_path)
    downloader = Downloader(config=config, security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]), transport=transport)

    first = downloader.download("https://example.com/a.pdf", allowed_domains=["example.com"])
    second = downloader.download("https://example.com/a.pdf", allowed_domains=["example.com"])

    assert first.sha256 == expected_sha
    assert second.sha256 == expected_sha
    assert first.file_path == second.file_path
    assert (tmp_path / expected_sha[:2] / f"{expected_sha}.pdf").exists()


def test_downloader_rejects_unsupported_content_type(tmp_path):
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(url=url, final_url=url, status_code=200, headers={"content-type": "text/html"}, body=b"<html></html>")

    downloader = Downloader(
        config=WebAcquisitionConfig(downloads_dir=tmp_path),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = downloader.download("https://example.com/a.html", allowed_domains=["example.com"])

    assert result.error_code == "unsupported_content_type"


def test_downloader_rejects_file_size_limit(tmp_path):
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(url=url, final_url=url, status_code=200, headers={"content-type": "application/pdf"}, body=b"x" * 12)

    downloader = Downloader(
        config=WebAcquisitionConfig(downloads_dir=tmp_path, max_file_size_bytes=10),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = downloader.download("https://example.com/big.pdf", allowed_domains=["example.com"])

    assert result.error_code == "file_too_large"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_acquisition_downloader.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.web_acquisition.downloader'`.

- [ ] **Step 3: Implement Downloader**

Create `app/web_acquisition/downloader.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.schemas import DownloadedFile, FetchResponse
from app.web_acquisition.security import SecurityGate, SecurityViolation


@dataclass(slots=True)
class DownloadOutcome:
    file: DownloadedFile | None = None
    error_code: str | None = None
    error_message: str = ""

    def __getattr__(self, name: str):
        if self.file is not None and hasattr(self.file, name):
            return getattr(self.file, name)
        raise AttributeError(name)


class Downloader:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        transport=None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.transport = transport or self._default_transport
        self._task_downloaded_bytes = 0

    def download(self, url: str, allowed_domains: list[str] | None = None) -> DownloadOutcome:
        try:
            self.security_gate.validate_url(url, allowed_domains=allowed_domains)
            response = self.transport(url, self.config.download_timeout_seconds, self.config.max_redirects)
            self.security_gate.validate_redirect_chain(url, response.redirect_chain, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return DownloadOutcome(error_code=exc.code, error_message=str(exc))
        except Exception as exc:
            return DownloadOutcome(error_code=type(exc).__name__, error_message=str(exc))

        if response.content_type != "application/pdf":
            return DownloadOutcome(error_code="unsupported_content_type", error_message=response.content_type)

        size = len(response.body)
        if size > self.config.max_file_size_bytes:
            return DownloadOutcome(error_code="file_too_large", error_message=str(size))
        if self._task_downloaded_bytes + size > self.config.max_total_download_bytes:
            return DownloadOutcome(error_code="task_download_limit_exceeded", error_message=str(size))

        digest = hashlib.sha256(response.body).hexdigest()
        directory = Path(self.config.downloads_dir) / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.pdf"
        if not path.exists():
            path.write_bytes(response.body)
        self._task_downloaded_bytes += size

        downloaded = DownloadedFile(
            source_url=url,
            final_url=response.final_url,
            file_path=str(path),
            filename=path.name,
            content_type=response.content_type,
            size_bytes=size,
            sha256=digest,
        )
        return DownloadOutcome(file=downloaded)

    def _default_transport(self, url: str, timeout_seconds: int, max_redirects: int) -> FetchResponse:
        request = Request(url, headers={"User-Agent": "insurance-web-acquisition/0.1"})
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(self.config.max_file_size_bytes + 1)
            return FetchResponse(
                url=url,
                final_url=response.geturl(),
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
                redirect_chain=[response.geturl()] if response.geturl() != url else [],
            )
```

- [ ] **Step 4: Run downloader tests**

Run: `pytest tests/test_web_acquisition_downloader.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web_acquisition/downloader.py tests/test_web_acquisition_downloader.py
git commit -m "feat: add safe web acquisition downloader"
```

## Task 7: Stage 1 Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run all Stage 1 tests**

Run:

```bash
pytest tests/test_web_acquisition_security.py tests/test_web_acquisition_extractor.py tests/test_web_acquisition_quality.py tests/test_web_acquisition_http_fetcher.py tests/test_web_acquisition_downloader.py -v
```

Expected: PASS for all Stage 1 tests.

- [ ] **Step 2: Run existing relevant test suites**

Run:

```bash
pytest tests/test_agent_tools.py tests/test_api_routes.py -v
```

Expected: PASS. These suites help confirm Stage 1 did not change the existing lightweight `web_fetch` tool or FastAPI route behavior.

- [ ] **Step 3: Inspect git status**

Run: `git status --short`

Expected: only intended Stage 1 files are modified or untracked. Existing unrelated user changes in `app/agents/transparent_runtime.py`, `app/api/routes.py`, `app/tools/agent_tools.py`, `tests/test_agent_tools.py`, `tests/test_transparent_runtime.py`, and `query_db.py` remain untouched.

- [ ] **Step 4: Commit final verification note if needed**

If a test-only adjustment was required during verification, commit it with:

```bash
git add app/web_acquisition tests/test_web_acquisition_*.py
git commit -m "test: verify web acquisition stage1"
```

## Self-Review

Spec coverage:

- Stage 1 package boundary maps to the approved `app/web_acquisition/` architecture.
- SecurityGate covers schemes, DNS/IP validation, allowed domains, and redirect limits.
- Extractor covers title, text, links, PDF links, button links, iframe links, script links, relative URL resolution, and document classification.
- FastHttpFetcher covers ordinary HTTP, content type filtering, extraction, quality scoring, partial failure, and redirect recording.
- Downloader covers safety validation, PDF content type, size limits, SHA-256, and dedupe.

Known Stage Boundaries:

- BrowserPool, PlaywrightFetcher, BrowserUseAgentFetcher, SiteSpecificHarness, WebAcquisitionService, FastAPI routes, and SQLite acquisition tables are intentionally excluded from this Stage 1 plan and require follow-on implementation plans.

Gap scan:

- The plan contains no open-ended gaps and gives exact files, tests, commands, expected outcomes, and implementation code for Stage 1.

Type consistency:

- `AcquisitionResult`, `AcquisitionStep`, `AcquisitionError`, `DiscoveredLink`, `DownloadedFile`, `ExtractedContent`, and `FetchResponse` are defined before use.
- `SecurityGate`, `Extractor`, `score_quality`, `FastHttpFetcher`, and `Downloader` signatures are consistent across tests and implementation snippets.
