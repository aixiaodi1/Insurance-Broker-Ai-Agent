from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.memory.schemas import ToolResult
from app.tools.agent_tools import local_read, local_search, run_cli, web_fetch, web_search
from app.tools.identity_tools import resolve_product_alias
from app.tools.local_sources import search_local_specs
from app.tools.rag_tools import rag_search


def _build_tools() -> dict[str, BaseTool]:
    return {
        "search_local_specs": StructuredTool.from_function(
            search_local_specs,
            name="search_local_specs",
            description="Search curated local insurance product specs by company or product name.",
        ),
        "local_search": StructuredTool.from_function(
            local_search,
            name="local_search",
            description="Search text files in the configured local source root.",
        ),
        "local_read": StructuredTool.from_function(
            local_read,
            name="local_read",
            description="Read a supported local text file with a character limit.",
        ),
        "run_cli": StructuredTool.from_function(
            run_cli,
            name="run_cli",
            description="Run a narrowly allowlisted local inspection command such as rg, ls, dir, or Get-ChildItem.",
        ),
        "web_search": StructuredTool.from_function(
            web_search,
            name="web_search",
            description="Search the web for candidate public source pages.",
        ),
        "web_fetch": StructuredTool.from_function(
            web_fetch,
            name="web_fetch",
            description="Fetch and extract plain text from a public URL.",
        ),
        "resolve_product_alias": StructuredTool.from_function(
            resolve_product_alias,
            name="resolve_product_alias",
            description="Resolve a product name and aliases into a canonical identity candidate.",
        ),
        "rag_search": StructuredTool.from_function(
            rag_search,
            name="rag_search",
            description="Placeholder RAG search. Returns no formal citations until a corpus is configured.",
        ),
    }


TOOLS_BY_NAME = _build_tools()

NODE_TOOL_ALLOWLIST: Mapping[str, tuple[str, ...]] = {
    "global_router": ("local_search", "resolve_product_alias"),
    "local_evidence_search": ("search_local_specs", "local_search", "local_read"),
    "web_lead_search": ("web_search", "web_fetch"),
    "product_identity_resolve": ("resolve_product_alias",),
    "rag_citation_check": ("rag_search",),
}


def get_node_tools(node_name: str) -> list[BaseTool]:
    return [TOOLS_BY_NAME[name] for name in NODE_TOOL_ALLOWLIST.get(node_name, ()) if name in TOOLS_BY_NAME]


def get_node_tool_specs(node_name: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for tool in get_node_tools(node_name):
        args_schema = getattr(tool, "args_schema", None)
        parameters = args_schema.model_json_schema() if args_schema is not None else {"type": "object", "properties": {}}
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": parameters,
                },
            }
        )
    return specs


def get_all_tool_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for tool in TOOLS_BY_NAME.values():
        args_schema = getattr(tool, "args_schema", None)
        parameters = args_schema.model_json_schema() if args_schema is not None else {"type": "object", "properties": {}}
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": parameters,
                },
            }
        )
    return specs


def execute_node_tool(node_name: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    allowed_names = set(NODE_TOOL_ALLOWLIST.get(node_name, ()))
    if tool_name not in allowed_names:
        return ToolResult(
            ok=False,
            source="tool_registry",
            data={"node": node_name, "tool": tool_name, "allowed_tools": sorted(allowed_names)},
            error="tool_not_allowed_for_node",
        )

    tool = TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return ToolResult(
            ok=False,
            source="tool_registry",
            data={"node": node_name, "tool": tool_name},
            error="tool_not_registered",
        )

    try:
        output = tool.invoke(arguments)
    except Exception as exc:  # pragma: no cover - exact tool failures vary by environment.
        return ToolResult(
            ok=False,
            source=tool_name,
            data={"node": node_name, "tool": tool_name},
            error=type(exc).__name__,
        )

    if isinstance(output, ToolResult):
        return output
    if isinstance(output, dict):
        return ToolResult(ok=True, source=tool_name, data=output)
    return ToolResult(ok=True, source=tool_name, data={"output": output})


def execute_tool(tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    tool = TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return ToolResult(
            ok=False,
            source="tool_registry",
            data={"tool": tool_name},
            error="tool_not_registered",
        )
    try:
        output = tool.invoke(arguments)
    except Exception as exc:  # pragma: no cover - exact tool failures vary by environment.
        return ToolResult(
            ok=False,
            source=tool_name,
            data={"tool": tool_name},
            error=type(exc).__name__,
        )
    if isinstance(output, ToolResult):
        return output
    if isinstance(output, dict):
        return ToolResult(ok=True, source=tool_name, data=output)
    return ToolResult(ok=True, source=tool_name, data={"output": output})
