from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EvidenceItem(BaseModel):
    title: str
    company_name: str | None = None
    product_name: str | None = None
    source_url: str | None = None
    source_tier: str = "S5"
    material_type: str | None = None
    file_hash: str | None = None
    page: int | None = None
    chunk_id: str | None = None
