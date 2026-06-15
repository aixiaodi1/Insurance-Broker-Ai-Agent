from typing import Any

from app.config import settings
from app.tools.registry import execute_node_tool


def local_evidence_search(state: dict[str, Any]) -> dict[str, Any]:
    result = execute_node_tool(
        "local_evidence_search",
        "search_local_specs",
        {"company_name": state.get("company_name"), "product_name": state.get("product_name")},
    )
    state["local_candidates"] = result.data.get("candidates", [])
    query = state.get("product_name") or state.get("user_input", "")
    search_result = execute_node_tool("local_evidence_search", "local_search", {"query": query})
    _record_tool_event(state, "local_evidence_search", "local_search", {"query": query}, search_result.data, search_result.ok, search_result.error)
    for match in search_result.data.get("matches", []):
        candidate = {
            "title": f"本地文件：{match.get('path')}",
            "source_tier": "LOCAL",
            "source_url": None,
            "file_path": match.get("path"),
            "line": match.get("line"),
            "excerpt": match.get("excerpt"),
        }
        state["local_candidates"].append(candidate)
        state.setdefault("source_observations", []).append(candidate)

    for candidate in list(state.get("local_candidates", []))[:3]:
        file_path = candidate.get("file_path")
        if not file_path:
            continue
        read_result = execute_node_tool("local_evidence_search", "local_read", {"path": file_path})
        _record_tool_event(
            state,
            "local_evidence_search",
            "local_read",
            {"path": file_path},
            {"path": file_path, "chars": len(read_result.data.get("text", ""))},
            read_result.ok,
            read_result.error,
        )
        if read_result.ok:
            candidate["excerpt"] = read_result.data.get("text", candidate.get("excerpt"))
    return state


def web_lead_search(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("local_candidates"):
        return state
    if not settings.enable_web_search:
        state["web_leads"] = []
        state["stop_reasons"].append(
            {
                "code": "official_evidence_not_closed",
                "message": "本地和网络线索暂未形成官网证据闭环",
            }
        )
        return state
    query = state.get("product_name") or state.get("user_input", "")
    result = execute_node_tool("web_lead_search", "web_search", {"query": query})
    state["web_leads"] = result.data.get("results", [])
    _record_tool_event(state, "web_lead_search", "web_search", {"query": query}, result.data, result.ok, result.error)

    for lead in state["web_leads"][:2]:
        url = lead.get("url")
        if not url:
            continue
        fetched = execute_node_tool("web_lead_search", "web_fetch", {"url": url})
        observation = {
            "title": lead.get("title") or url,
            "source_tier": "WEB",
            "source_url": url,
            "file_path": None,
            "excerpt": fetched.data.get("text", "")[:800] if fetched.ok else "",
        }
        state.setdefault("source_observations", []).append(observation)
        _record_tool_event(
            state,
            "web_lead_search",
            "web_fetch",
            {"url": url},
            {"url": url, "chars": len(observation["excerpt"])},
            fetched.ok,
            fetched.error,
        )

    if not state.get("source_observations"):
        state["stop_reasons"].append(
            {
                "code": "official_evidence_not_closed",
                "message": "本地和网络线索暂未形成官网证据闭环",
            }
        )
    return state


def product_identity_resolve(state: dict[str, Any]) -> dict[str, Any]:
    result = execute_node_tool(
        "product_identity_resolve",
        "resolve_product_alias",
        {"product_name": state.get("product_name"), "aliases": state.get("aliases", [])},
    )
    state["product_identity"] = result.data if result.ok else None
    return state


def rag_citation_check(state: dict[str, Any]) -> dict[str, Any]:
    result = execute_node_tool(
        "rag_citation_check",
        "rag_search",
        {"query": state.get("product_name") or state.get("user_input", "")},
    )
    state["rag_citations"] = result.data.get("citations", [])
    state["rag_status"] = {
        "status": result.data.get("status", "unknown"),
        "configured": result.data.get("configured", False),
    }
    return state


def evidence_score(state: dict[str, Any]) -> dict[str, Any]:
    official_points = 30 if state.get("official_sources") else 0
    identity_points = 20 if state.get("product_identity") else 0
    citation_points = 20 if state.get("rag_citations") else 0
    if not citation_points and state.get("source_observations"):
        citation_points = 10
    total = official_points + identity_points + citation_points
    state["evidence_score"] = {
        "official_evidence": official_points,
        "product_identity": identity_points,
        "citations": citation_points,
        "total": total,
    }
    return state


def _record_tool_event(
    state: dict[str, Any],
    node: str,
    tool: str,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    ok: bool,
    error: str | None,
) -> None:
    state.setdefault("tool_events", []).append(
        {
            "node": node,
            "tool": tool,
            "status": "success" if ok else "fail",
            "input_summary": input_summary,
            "output_summary": output_summary,
            "error": error,
        }
    )
