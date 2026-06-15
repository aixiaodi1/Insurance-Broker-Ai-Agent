def test_registry_exposes_only_tools_allowed_for_fixed_node():
    from app.tools.registry import get_node_tools

    local_tools = get_node_tools("local_evidence_search")
    names = {tool.name for tool in local_tools}

    assert {"local_search", "local_read"}.issubset(names)
    assert "web_search" not in names
    assert "rag_search" not in names


def test_execute_node_tool_rejects_tools_outside_node_allowlist():
    from app.tools.registry import execute_node_tool

    result = execute_node_tool(
        "local_evidence_search",
        "web_search",
        {"query": "AlphaCare"},
    )

    assert result.ok is False
    assert result.source == "tool_registry"
    assert result.error == "tool_not_allowed_for_node"


def test_registry_tools_return_standard_tool_result_payload(tmp_path):
    from app.tools.registry import execute_node_tool

    source = tmp_path / "notes.md"
    source.write_text("AlphaCare official evidence", encoding="utf-8")

    result = execute_node_tool(
        "local_evidence_search",
        "local_search",
        {"query": "AlphaCare", "root": str(tmp_path), "limit": 3},
    )

    assert result.ok is True
    assert result.source == "local_search"
    assert result.data["matches"][0]["path"] == str(source)


def test_unknown_node_has_no_tools():
    from app.tools.registry import get_node_tools

    assert get_node_tools("report") == []


def test_global_router_has_only_safe_triage_tools():
    from app.tools.registry import get_node_tools

    names = {tool.name for tool in get_node_tools("global_router")}

    assert names == {"local_search", "resolve_product_alias"}
