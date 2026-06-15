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
