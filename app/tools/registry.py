"""B1.4 — tool registry.

Registers tools, emits OpenAI tool schemas filtered by the user's permission matrix (the model only
ever sees actions it's allowed to take), and resolves tools by name for dispatch.

Each tool declares the permission it needs via ``required_permission = (resource, action)``. Read-tier
tools may omit it (always visible). A tool whose permission the user lacks is hidden from the model.
"""

from __future__ import annotations

from app.contracts.types import PermissionMatrix, Tool


class UnknownToolError(KeyError):
    """Raised when dispatching to a tool name that was never registered."""


def _required_permission(tool: Tool) -> tuple[str, str] | None:
    return getattr(tool, "required_permission", None)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def visible_tools(self, perms: PermissionMatrix) -> list[Tool]:
        """Tools the user is permitted to use (read-tier always visible)."""
        visible: list[Tool] = []
        for tool in self._tools.values():
            req = _required_permission(tool)
            if req is None or tool.risk_tier == "read":
                visible.append(tool)
            elif perms.can(req[0], req[1]):
                visible.append(tool)
        return visible

    def openai_tools(self, perms: PermissionMatrix) -> list[dict]:
        """Emit strict OpenAI function-tool schemas for the visible tools."""
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "strict": True,
                "parameters": tool.parameters_schema,
            }
            for tool in self.visible_tools(perms)
        ]

    def has_mutating_tool(self, perms: PermissionMatrix) -> bool:
        """True if any visible tool is draft/publish tier (⇒ parallel_tool_calls must be False)."""
        return any(t.risk_tier in {"draft", "publish"} for t in self.visible_tools(perms))
