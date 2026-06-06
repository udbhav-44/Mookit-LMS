"""B1.5 — common read-tier tools backed by MooKitClient.

  * WhoAmITool            — GET /users/me
  * ResolveTaxonomyTool   — resolve "Week 4" / "Module 2" → weekId/topicId via /taxonomies/{type}
  * PermissionIntrospectTool — what can the current user do?

All read-tier. mooKIT-returned text is treated as untrusted (spotlighting enforced at the context
boundary in P4); these tools only return structured fields, never free instructions.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.contracts import RequestContext, Tool, ToolResult
from app.contracts.mookit import MooKitClient
from app.llm.schema import strict_schema


class _NoArgs(BaseModel):
    pass


class WhoAmITool(Tool):
    name = "whoami"
    description = "Get the current instructor's profile (id, name, email)."
    risk_tier = "read"
    parameters_schema = strict_schema(_NoArgs)

    def __init__(self, mookit: MooKitClient) -> None:
        self._mookit = mookit

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        user = await self._mookit.users_me(ctx)
        return ToolResult(ok=True, data=user.model_dump())


class ResolveTaxonomyArgs(BaseModel):
    type: str  # "week" | "module" | "topic" | "section"
    label: str  # e.g. "Week 4"


class ResolveTaxonomyTool(Tool):
    name = "resolve_taxonomy"
    description = (
        "Resolve a human label like 'Week 4' or 'Module 2' to its taxonomy term id. "
        "Returns the matched id, or candidates if the label is ambiguous/unknown."
    )
    risk_tier = "read"
    parameters_schema = strict_schema(ResolveTaxonomyArgs)

    def __init__(self, mookit: MooKitClient) -> None:
        self._mookit = mookit

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = ResolveTaxonomyArgs.model_validate(args)
        terms = await self._mookit.list_taxonomy(ctx, parsed.type)
        candidates = [{"id": t.id, "title": t.name} for t in terms]
        target = _normalize(parsed.label)
        exact = [t for t in terms if _normalize(t.name) == target]
        matched = exact[0].id if exact else None
        return ToolResult(
            ok=True,
            data={
                "matched": matched,
                "matched_title": exact[0].name if exact else None,
                "candidates": candidates,
            },
            message=(
                f"Resolved '{parsed.label}' to id {matched}."
                if matched is not None
                else f"No exact match for '{parsed.label}'; {len(candidates)} candidates available."
            ),
        )


class PermissionIntrospectTool(Tool):
    name = "my_permissions"
    description = "List the actions the current instructor is permitted to perform in this course."
    risk_tier = "read"
    parameters_schema = strict_schema(_NoArgs)

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data=ctx.permissions.resources)


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())
