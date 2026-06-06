"""B0.4 acceptance — EchoTool schema is strict and run echoes."""

from app.contracts import RequestContext, Tool, ToolResult
from app.tools.echo import EchoTool


def test_echo_schema_is_strict() -> None:
    schema = EchoTool.parameters_schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"text"}


def test_echo_is_read_tier() -> None:
    assert EchoTool.risk_tier == "read"


def test_echo_registers_as_tool() -> None:
    assert isinstance(EchoTool(), Tool)


async def test_echo_runs(ctx: RequestContext) -> None:
    result = await EchoTool().run(ctx, {"text": "ping"})
    assert isinstance(result, ToolResult)
    assert result.ok and result.data == {"echo": "ping"}
