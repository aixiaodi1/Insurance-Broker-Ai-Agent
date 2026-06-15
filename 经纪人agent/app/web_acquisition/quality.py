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
