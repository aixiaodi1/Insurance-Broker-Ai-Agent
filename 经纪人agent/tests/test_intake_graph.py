from app.agents.graphs.intake_graph import run_intake_graph
from app.agents.state import new_agent_state


def test_intake_graph_routes_product_research():
    state = new_agent_state("user-1", "帮我查众民保官方资料", "user-1:task-1")
    result = run_intake_graph(state)
    assert result["task_type"] == "official_evidence_research"
    assert result["product_name"] == "众民保"
    assert result["user_visible_steps"][0]["title"] == "我先帮你确认要查的产品"
