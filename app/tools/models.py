"""结构化工具结果模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    source: str
    license: str = ""
    dataset_version: str = ""
    result_hash: str = ""
    ok: bool = True
    error: str | None = None
