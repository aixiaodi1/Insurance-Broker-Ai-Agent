from app.memory.schemas import ToolResult


def query_iachina_property_product(company_name: str | None, product_name: str | None) -> ToolResult:
    return ToolResult(
        ok=False,
        source="iachina",
        data={"company_name": company_name, "product_name": product_name, "status": "not_configured"},
        error="中保协查询工具尚未接入，需要人工或浏览器会话",
    )
