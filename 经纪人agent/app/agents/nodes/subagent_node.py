from __future__ import annotations

from typing import Any

from app.subagent.runner import SubagentRunner


async def evidence_search_with_subagent(
    state: dict[str, Any],
    runner: SubagentRunner,
) -> dict[str, Any]:
    state = dict(state)
    product_name = state.get("product_name") or state.get("user_input", "")

    result = await runner.spawn(
        "evidence_searcher",
        {
            "product_name": product_name,
            "max_results": 5,
        },
        parent_trace_id=state.get("run_id", "main"),
    )

    if result.status == "success":
        items = result.result.get("items", []) if isinstance(result.result, dict) else []
        state["evidence_items"] = items
        state["search_trace_id"] = result.trace.trace_id
        state["source_observations"] = [
            {
                "title": item.get("title", ""),
                "source_tier": item.get("source_tier", "S5"),
                "source_url": item.get("url"),
                "confidence": item.get("confidence"),
                "reasoning": item.get("reasoning"),
            }
            for item in items
        ]
        state["stop_reasons"] = [
            r for r in state.get("stop_reasons", [])
            if r.get("code") != "official_evidence_not_closed"
        ]
    else:
        state["search_trace_id"] = result.trace.trace_id
        state["search_error"] = {
            "status": result.status,
            "message": result.error_message,
        }
        state["stop_reasons"].append({
            "code": "subagent_search_failed",
            "message": f"证据搜索 subagent 返回: {result.error_message or result.status}",
        })

    state["tool_events"].append({
        "node": "evidence_search_subagent",
        "tool": "spawn(evidence_searcher)",
        "status": result.status,
        "input_summary": {"product_name": product_name},
        "output_summary": {
            "items_count": len(state.get("evidence_items", [])),
            "trace_id": result.trace.trace_id,
            "tokens": result.trace.tokens_used,
        },
    })

    return state


async def citation_verify_with_subagent(
    state: dict[str, Any],
    runner: SubagentRunner,
) -> dict[str, Any]:
    state = dict(state)
    observations = state.get("source_observations", [])
    if not observations:
        return state

    verified = []
    for obs in observations[:3]:
        url = obs.get("source_url")
        if not url:
            continue
        result = await runner.spawn(
            "citation_verifier",
            {
                "claim": obs.get("title", ""),
                "source_url": url,
            },
            parent_trace_id=state.get("run_id", "main"),
        )
        verified.append({
            "url": url,
            "verdict": result.result.get("verdict") if isinstance(result.result, dict) else None,
            "match_score": result.result.get("match_score") if isinstance(result.result, dict) else None,
            "trace_id": result.trace.trace_id,
            "status": result.status,
        })

    state["citation_verifications"] = verified
    state["tool_events"].append({
        "node": "citation_verify_subagent",
        "tool": "spawn_many(citation_verifier)",
        "status": "success",
        "input_summary": {"observations_count": len(observations)},
        "output_summary": {"verified_count": len(verified)},
    })

    return state
