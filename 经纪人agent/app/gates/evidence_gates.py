from typing import Any


def evidence_gate(state: dict[str, Any]) -> dict[str, Any]:
    official_sources = state.get("official_sources") or []
    rag_citations = state.get("rag_citations") or []
    allowed = bool(official_sources and rag_citations)
    return {
        "allowed": allowed,
        "route": "generate_formal_report" if allowed else "generate_user_friendly_summary",
        "reason": None if allowed else "官方证据或RAG引用不足",
    }


def verify_before_rag_gate(state: dict[str, Any]) -> dict[str, Any]:
    pdf_assets = state.get("pdf_assets") or []
    invalid = [item for item in pdf_assets if item.get("is_valid_pdf") is False]
    return {
        "allowed": not invalid,
        "reason": None if not invalid else "存在未通过PDF魔数校验的材料",
    }
