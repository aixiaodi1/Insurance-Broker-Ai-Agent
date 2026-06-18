from app.tools.identity_tools import resolve_product_alias
from app.tools.local_sources import search_local_specs


PRODUCT_NAME = "\u4f17\u6c11\u4fdd"
USER_MESSAGE = "\u5e2e\u6211\u67e5\u4f17\u6c11\u4fdd\u5b98\u65b9\u8d44\u6599"


def test_search_local_specs_returns_tool_result():
    result = search_local_specs(company_name=PRODUCT_NAME, product_name=None)
    assert result.ok is True
    assert result.source == "local_specs"
    assert "candidates" in result.data


def test_resolve_product_alias_returns_identity_candidate():
    result = resolve_product_alias(product_name=PRODUCT_NAME, aliases=[PRODUCT_NAME])
    assert result.ok is True
    assert result.data["product_name"] == PRODUCT_NAME


def test_evidence_graph_records_missing_evidence_for_empty_local_results(monkeypatch):
    from app.config import settings
    from app.agents.graphs.evidence_graph import run_evidence_graph
    from app.agents.state import new_agent_state

    monkeypatch.setattr(settings, "local_source_root", settings.data_dir / "missing-local-source-root")
    monkeypatch.setattr(settings, "enable_web_search", False)
    state = new_agent_state("user-1", USER_MESSAGE, "user-1:task-1")
    state["product_name"] = PRODUCT_NAME
    result = run_evidence_graph(state)
    assert result["product_identity"]["product_name"] == PRODUCT_NAME
    assert result["evidence_score"]["total"] < 60
    assert result["stop_reasons"][0]["code"] == "official_evidence_not_closed"


def test_rag_search_is_placeholder_until_corpus_is_configured():
    from app.tools.rag_tools import rag_search

    result = rag_search(PRODUCT_NAME)

    assert result.ok is True
    assert result.data["citations"] == []
    assert result.data["status"] == "placeholder"
    assert result.data["configured"] is False


def test_evidence_graph_does_not_score_rag_placeholder_as_citation(monkeypatch):
    from app.config import settings
    from app.agents.graphs.evidence_graph import run_evidence_graph
    from app.agents.state import new_agent_state

    monkeypatch.setattr(settings, "local_source_root", settings.data_dir / "missing-local-source-root")
    monkeypatch.setattr(settings, "enable_web_search", False)
    state = new_agent_state("user-1", USER_MESSAGE, "user-1:task-1")
    state["product_name"] = PRODUCT_NAME
    result = run_evidence_graph(state)

    assert result["rag_citations"] == []
    assert result["rag_status"]["status"] == "placeholder"
    assert result["evidence_score"]["citations"] == 0


def test_local_candidates_do_not_skip_web_search(monkeypatch):
    import app.agents.nodes.evidence_nodes as evidence_nodes

    calls = []

    def fake_execute(node_name, tool_name, arguments):
        calls.append(tool_name)
        if tool_name == "web_search":
            return type("Result", (), {"ok": True, "data": {"results": []}, "error": None})()
        return type("Result", (), {"ok": True, "data": {}, "error": None})()

    monkeypatch.setattr(evidence_nodes, "execute_node_tool", fake_execute)
    state = {
        "local_candidates": [{"file_path": "local.md"}],
        "product_name": "御享金越",
        "user_input": "查询御享金越最新官方条款",
        "source_observations": [],
        "stop_reasons": [],
    }

    evidence_nodes.web_lead_search(state)

    assert "web_search" in calls
