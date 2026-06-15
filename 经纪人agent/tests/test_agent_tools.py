def test_local_search_finds_matching_file(tmp_path):
    from app.tools.agent_tools import local_search

    target = tmp_path / "notes.md"
    target.write_text("AlphaCare official local marker", encoding="utf-8")

    result = local_search("AlphaCare", root=tmp_path)

    assert result.ok is True
    assert result.source == "local_search"
    assert result.data["matches"]
    assert result.data["matches"][0]["path"] == str(target)


def test_run_cli_allows_rg_and_rejects_unknown_command(tmp_path):
    from app.tools.agent_tools import run_cli

    target = tmp_path / "notes.md"
    target.write_text("alpha official evidence", encoding="utf-8")

    allowed = run_cli("rg alpha .", cwd=tmp_path)
    rejected = run_cli("Remove-Item notes.md", cwd=tmp_path)

    assert allowed.ok is True
    assert "alpha official evidence" in allowed.data["stdout"]
    assert rejected.ok is False
    assert rejected.error == "command_not_allowed"
    assert target.exists()


def test_unified_tool_registry_exposes_local_search_and_cli_for_react(tmp_path):
    from app.tools.registry import execute_tool, get_all_tool_specs

    source_file = tmp_path / "alpha-product.md"
    source_file.write_text("AlphaCare local marker", encoding="utf-8")

    specs = get_all_tool_specs()
    tool_names = {item["function"]["name"] for item in specs}
    search_result = execute_tool("local_search", {"query": "AlphaCare", "root": str(tmp_path)})
    cli_result = execute_tool("run_cli", {"command": "rg AlphaCare .", "cwd": str(tmp_path)})

    assert {"local_search", "local_read", "run_cli", "web_search", "web_fetch"}.issubset(tool_names)
    assert search_result.ok is True
    assert search_result.data["matches"][0]["path"] == str(source_file)
    assert cli_result.ok is True
    assert "AlphaCare local marker" in cli_result.data["stdout"]


def test_web_fetch_extracts_readable_text_and_filters_script_noise(monkeypatch):
    import app.tools.agent_tools as agent_tools

    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            return b"""
            <html>
              <head>
                <style>.hidden { display: none; }</style>
                <script>window.__DATA__ = {"noisy": true};</script>
              </head>
              <body>
                <nav>Home Products Login</nav>
                <main>
                  <h1>Official Tool Reference</h1>
                  <p>The default runtime tools are listed in this document.</p>
                </main>
              </body>
            </html>
            """

    monkeypatch.setattr(agent_tools, "urlopen", lambda request, timeout=10: FakeResponse())

    result = agent_tools.web_fetch("https://docs.example.test/tools")

    assert result.ok is True
    assert "Official Tool Reference" in result.data["text"]
    assert "default runtime tools" in result.data["text"]
    assert "window.__DATA__" not in result.data["text"]
    assert "display: none" not in result.data["text"]
    assert result.data["content_kind"] == "webpage_text"


def test_web_search_deduplicates_results(monkeypatch):
    import app.tools.agent_tools as agent_tools
    from app.memory.schemas import ToolResult

    raw_html = """
    <h2><a href="https://docs.example.test/tools">Tools</a></h2>
    <h2><a href="https://docs.example.test/tools">Tools Duplicate</a></h2>
    <h2><a href="https://github.com/example/project">Project</a></h2>
    """
    monkeypatch.setattr(
        agent_tools,
        "web_fetch",
        lambda url, max_chars=160000: ToolResult(
            ok=True,
            source="web_fetch",
            data={"raw_html": raw_html, "text": "Tools Project"},
        ),
    )

    result = agent_tools.web_search("example project tools", limit=5)

    assert result.ok is True
    assert [item["url"] for item in result.data["results"]] == [
        "https://docs.example.test/tools",
        "https://github.com/example/project",
    ]
