from app.agents.graphs.report_graph import run_report_graph
from app.agents.state import new_agent_state


def test_report_graph_generates_novice_summary_when_score_is_low():
    state = new_agent_state("user-1", "帮我查众民保官方资料", "user-1:task-1")
    state["product_name"] = "众民保"
    state["evidence_score"] = {"total": 20}
    state["stop_reasons"] = [{"message": "官网证据未闭环"}]
    result = run_report_graph(state)
    assert "我查到了什么" in result["final_summary"]
    assert "官网证据未闭环" in result["final_summary"]
