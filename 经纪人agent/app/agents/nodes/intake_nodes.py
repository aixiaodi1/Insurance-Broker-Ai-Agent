from typing import Any


def novice_intake(state: dict[str, Any]) -> dict[str, Any]:
    text = state.get("user_input", "")
    product_name = "众民保" if "众民保" in text else state.get("product_name")
    state["product_name"] = product_name
    state["aliases"] = [product_name] if product_name else []
    state["user_visible_steps"].append(
        {
            "title": "我先帮你确认要查的产品",
            "detail": product_name or "还没有识别出明确产品名",
        }
    )
    return state


def task_router(state: dict[str, Any]) -> dict[str, Any]:
    state["task_type"] = "official_evidence_research"
    return state
