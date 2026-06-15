from app.memory.schemas import ToolResult


def resolve_product_alias(product_name: str | None, aliases: list[str]) -> ToolResult:
    canonical = product_name or (aliases[0] if aliases else None)
    return ToolResult(
        ok=canonical is not None,
        source="identity",
        data={
            "product_name": canonical,
            "aliases": aliases,
            "components": [],
        },
        error=None if canonical else "缺少产品名",
    )
