from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_markdown_files_exist_and_describe_runtime_sources():
    required = [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "TOOLS.md",
        "BOOTSTRAP.md",
        "MEMORY.md",
        "Skills.md",
        "SUB_AGENTS.md",
        "PROVIDERS.md",
    ]

    for name in required:
        path = ROOT / name
        assert path.exists(), f"{name} should exist at project root"
        assert path.read_text(encoding="utf-8").strip(), f"{name} should not be empty"

    tools_text = (ROOT / "TOOLS.md").read_text(encoding="utf-8")
    assert "local_search" in tools_text
    assert "web_fetch" in tools_text
    assert "run_cli" in tools_text

    subagents_text = (ROOT / "SUB_AGENTS.md").read_text(encoding="utf-8")
    assert "evidence_searcher" in subagents_text
    assert "citation_verifier" in subagents_text

    providers_text = (ROOT / "PROVIDERS.md").read_text(encoding="utf-8")
    assert "LLM_API_BASE_URL" in providers_text
    assert "LLM_MODEL" in providers_text
    assert "MINIMAX_API_KEY" in providers_text


def test_agent_context_assembler_injects_docs_tools_subagents_provider_and_time():
    from app.agents.bootstrap_context import AgentContextAssembler

    context = AgentContextAssembler(project_root=ROOT).build()

    assert context["current_datetime"]
    assert context["provider"]["llm_provider"]
    assert "AGENTS.md" in context["documents"]
    assert "BOOTSTRAP.md" in context["documents"]
    assert "TOOLS.md" in context["documents"]
    assert "local_search" in {tool["name"] for tool in context["tools"]}
    assert "web_search" in {tool["name"] for tool in context["tools"]}
    assert "evidence_searcher" in {item["name"] for item in context["sub_agents"]}
    assert "citation_verifier" in {item["name"] for item in context["sub_agents"]}


def test_public_planning_schema_is_open_ended_not_fixed_route_categories():
    from app.agents.transparent_planning import PUBLIC_PLANNING_SCHEMA

    schema_text = str(PUBLIC_PLANNING_SCHEMA)
    assert "intent_anchor" in PUBLIC_PLANNING_SCHEMA["properties"]
    assert "task_decomposition" in PUBLIC_PLANNING_SCHEMA["properties"]
    assert "hypotheses" in schema_text
    assert "verification_paths" in schema_text
    assert "identity" not in schema_text
    assert "clarification" not in schema_text
    assert "official_evidence_research" not in schema_text
