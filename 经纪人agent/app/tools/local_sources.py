from app.memory.schemas import ToolResult


def search_local_specs(company_name: str | None, product_name: str | None) -> ToolResult:
    query = company_name or product_name or ""
    return ToolResult(
        ok=True,
        source="local_specs",
        data={
            "query": query,
            "candidates": [],
        },
    )
