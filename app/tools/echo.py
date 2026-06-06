"""B0.4 — EchoTool: a minimal read-tier tool so the bare loop round-trips at CP1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.contracts.types import RequestContext, Tool, ToolResult
from app.llm.schema import strict_schema


class EchoArgs(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    description = "Echo back the provided text. Used for connectivity testing."
    risk_tier = "read"
    parameters_schema = strict_schema(EchoArgs)

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = EchoArgs.model_validate(args)
        return ToolResult(ok=True, data={"echo": parsed.text}, message=parsed.text)
