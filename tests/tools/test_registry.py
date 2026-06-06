"""B1.4 acceptance — permission filtering, strict schema emission, unknown-tool error."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.contracts import PermissionMatrix, RequestContext, Tool, ToolResult
from app.llm.schema import strict_schema
from app.tools.echo import EchoTool
from app.tools.registry import ToolRegistry, UnknownToolError


class _Args(BaseModel):
    x: str


class _PublishThing(Tool):
    name = "publish_thing"
    description = "publish a thing"
    risk_tier = "publish"
    parameters_schema = strict_schema(_Args)
    required_permission = ("things", "publish")

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(_PublishThing())
    return reg


def test_read_tool_always_visible_publish_hidden_without_perm() -> None:
    reg = _registry()
    perms = PermissionMatrix(resources={})  # no permissions
    names = [t["name"] for t in reg.openai_tools(perms)]
    assert "echo" in names
    assert "publish_thing" not in names


def test_publish_tool_visible_with_perm() -> None:
    reg = _registry()
    perms = PermissionMatrix(resources={"things": ["publish"]})
    names = [t["name"] for t in reg.openai_tools(perms)]
    assert "publish_thing" in names


def test_emitted_schema_is_strict() -> None:
    reg = _registry()
    perms = PermissionMatrix(resources={"things": ["publish"]})
    for t in reg.openai_tools(perms):
        assert t["strict"] is True
        assert t["parameters"]["additionalProperties"] is False


def test_unknown_tool_raises() -> None:
    with pytest.raises(UnknownToolError):
        _registry().get("nope")


def test_duplicate_registration_raises() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(EchoTool())


def test_has_mutating_tool_reflects_visibility() -> None:
    reg = _registry()
    assert reg.has_mutating_tool(PermissionMatrix(resources={"things": ["publish"]})) is True
    assert reg.has_mutating_tool(PermissionMatrix(resources={})) is False
