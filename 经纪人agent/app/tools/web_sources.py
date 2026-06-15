from app.memory.schemas import ToolResult


def web_extract(query: str) -> ToolResult:
    return ToolResult(ok=True, source="web_extract", data={"query": query, "leads": []})
