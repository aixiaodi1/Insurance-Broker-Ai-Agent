from app.agents.nodes.report_nodes import generate_formal_report, generate_user_friendly_summary


def run_report_graph(state: dict) -> dict:
    score = (state.get("evidence_score") or {}).get("total", 0)
    if score >= 80:
        return generate_formal_report(state)
    return generate_user_friendly_summary(state)
