from pathlib import Path


def test_resolver_identifies_github_url_as_remote_project():
    from app.agents.resource_resolution import resolve_resource_context

    context = resolve_resource_context("github.com/JimLiu/baoyu-skills 你帮我看看这个项目有什么用", Path.cwd())

    assert context["resource_type"] == "github_repo"
    assert context["location"] == "remote"
    assert context["canonical_url"] == "https://github.com/JimLiu/baoyu-skills"
    assert context["resource_id"] == "JimLiu/baoyu-skills"
    assert context["task_type"] == "explain_project"
    assert context["primary_tools"] == ["web_fetch"]
    assert context["fallback_tools"] == ["web_search"]


def test_resolver_identifies_repo_slug_without_treating_it_as_local():
    from app.agents.resource_resolution import resolve_resource_context

    context = resolve_resource_context("JimLiu/baoyu-skills 这个项目有什么用", Path.cwd())

    assert context["resource_type"] == "github_repo"
    assert context["location"] == "remote"
    assert context["canonical_url"] == "https://github.com/JimLiu/baoyu-skills"
    assert context["local_search_recommended"] is False


def test_resolver_identifies_local_path_when_user_points_at_workspace_file(tmp_path):
    from app.agents.resource_resolution import resolve_resource_context

    target = tmp_path / "README.md"
    target.write_text("hello", encoding="utf-8")

    context = resolve_resource_context(f"帮我看看 {target}", tmp_path)

    assert context["resource_type"] == "local_path"
    assert context["location"] == "local"
    assert context["local_search_recommended"] is True
    assert context["canonical_url"] == ""


def test_resolver_identifies_npm_package_as_remote_resource():
    from app.agents.resource_resolution import resolve_resource_context

    context = resolve_resource_context("lodash 这个 npm 包有什么用", Path.cwd())

    assert context["resource_type"] == "package_name"
    assert context["location"] == "remote"
    assert context["resource_id"] == "lodash"
    assert context["package_registry"] == "npm"
    assert context["canonical_url"] == "https://www.npmjs.com/package/lodash"
    assert context["local_search_recommended"] is False


def test_resolver_identifies_pypi_package_as_remote_resource():
    from app.agents.resource_resolution import resolve_resource_context

    context = resolve_resource_context("requests 这个 PyPI 包是做什么的", Path.cwd())

    assert context["resource_type"] == "package_name"
    assert context["package_registry"] == "pypi"
    assert context["canonical_url"] == "https://pypi.org/project/requests/"


def test_public_planning_schema_exposes_resource_context():
    from app.agents.transparent_planning import PUBLIC_PLANNING_SCHEMA

    properties = PUBLIC_PLANNING_SCHEMA["properties"]

    assert "resource_context" in properties
    assert {"resource_type", "location", "task_type"}.issubset(properties["resource_context"]["required"])
