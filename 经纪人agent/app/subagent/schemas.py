from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class SubagentDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    tools: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    prompt: str


class SubagentTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: f"sub_{uuid4().hex[:12]}")
    parent_trace_id: str = ""
    turn_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    tokens_used: int = 0
    log: list[dict[str, Any]] = Field(default_factory=list)


class SubagentResult(BaseModel):
    status: Literal["success", "timeout", "schema_validation_failed", "error", "interrupted"]
    result: Any = None
    raw_output: str | None = None
    trace: SubagentTrace = Field(default_factory=SubagentTrace)
    error_message: str | None = None
