from typing import Any


def generate_user_friendly_summary(state: dict[str, Any]) -> dict[str, Any]:
    product = state.get("product_name") or "这个产品"
    reasons = state.get("stop_reasons") or []
    reason_text = "；".join(item.get("message", "") for item in reasons) or "暂无未闭环问题"
    citations = state.get("rag_citations") or []
    observations = state.get("source_observations") or []
    official_text = _format_sources(observations, citations)
    state["final_summary"] = (
        "## 我查到了什么\n"
        f"{_format_findings(product, observations)}\n\n"
        "## 哪些是官方证据\n"
        f"{official_text}\n\n"
        "## 还有哪些没确认\n"
        f"{reason_text}\n\n"
        "## 下一步你可以点什么\n"
        "你可以继续官网查找、上传PDF，或让人工复核产品名称。"
    )
    return state


def generate_formal_report(state: dict[str, Any]) -> dict[str, Any]:
    state["final_report"] = state.get("final_summary") or "正式报告生成成功。"
    return state


def _format_citations(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "目前还没有足够的官方证据进入正式报告。"
    lines = []
    for item in citations:
        title = item.get("title") or "未命名资料"
        source_tier = item.get("source_tier") or "S5"
        chunk_id = item.get("chunk_id") or "无chunk_id"
        source_url = item.get("source_url") or "无URL"
        lines.append(f"- {title}（{source_tier}，chunk_id: {chunk_id}，URL: {source_url}）")
    return "\n".join(lines)


def _format_sources(observations: list[dict[str, Any]], citations: list[dict[str, Any]]) -> str:
    lines = []
    for item in observations:
        title = item.get("title") or item.get("source_url") or item.get("file_path") or "未命名来源"
        source_tier = item.get("source_tier") or "SOURCE"
        locator = item.get("source_url") or item.get("file_path") or "无定位信息"
        lines.append(f"- {title}（{source_tier}，来源: {locator}）")
    citation_text = _format_citations(citations)
    if citation_text and "目前还没有" not in citation_text:
        lines.append(citation_text)
    if not lines:
        return "目前还没有足够的官方证据进入正式报告。"
    return "\n".join(lines)


def _format_findings(product: str, observations: list[dict[str, Any]]) -> str:
    if not observations:
        return f"我正在帮你查：{product}。"
    excerpts = []
    for item in observations[:3]:
        excerpt = (item.get("excerpt") or "").strip()
        if excerpt:
            excerpts.append(excerpt[:260])
    if not excerpts:
        return f"我正在帮你查：{product}，已经找到可继续复核的来源。"
    return "\n".join(f"- {excerpt}" for excerpt in excerpts)
