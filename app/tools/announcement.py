"""B3.2 — announcement tools.

  * DraftAnnouncementTool (draft) — create an announcement_draft artifact.
  * SendAnnouncementTool (publish) — propose sending; audience is an INTENT label (resolved
    server-side). Body is sanitized in the preview. NEVER calls mooKIT.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.contracts.types import (
    Artifact,
    ArtifactRegistry,
    ProposedAction,
    RequestContext,
    Tool,
    ToolResult,
)
from app.core.hashing import canonical_hash
from app.gen.announcement import draft_announcement
from app.gen.provenance import stamp
from app.llm.schema import strict_schema
from app.preview.render import build_announcement_preview, sanitize_markdown


class DraftAnnouncementArgs(BaseModel):
    intent: str
    audience: str = "all"  # intent label only


class DraftAnnouncementTool(Tool):
    name = "draft_announcement"
    description = "Draft an announcement (subject + body) from the instructor's intent."
    risk_tier = "draft"
    parameters_schema = strict_schema(DraftAnnouncementArgs)
    required_permission = ("announcements", "create")

    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = DraftAnnouncementArgs.model_validate(args)
        draft = await draft_announcement(intent=parsed.intent, audience_intent=parsed.audience)
        art = Artifact(
            id="",
            type="announcement_draft",
            title=draft.title,
            status="draft",
            payload=draft.model_dump(),
            provenance=stamp(ai_generated=True, edited_by_human=False, source_ids=[]),
        )
        art_id = await self._registry.add(ctx, art)
        return ToolResult(ok=True, artifact_id=art_id, data=draft.model_dump(), message="Drafted announcement.")


class SendAnnouncementArgs(BaseModel):
    draft_id: str


class SendAnnouncementTool(Tool):
    name = "send_announcement"
    description = "Propose sending an announcement draft (requires confirmation)."
    risk_tier = "publish"
    parameters_schema = strict_schema(SendAnnouncementArgs)
    required_permission = ("announcements", "publish")

    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ProposedAction:
        parsed = SendAnnouncementArgs.model_validate(args)
        draft = await self._registry.get(ctx, parsed.draft_id)
        if draft is None:
            raise KeyError(parsed.draft_id)
        d = draft.payload
        # The mooKIT payload carries the audience INTENT, not resolved ids; the gate resolves
        # sectionIds server-side. Empty/"all" => all students.
        payload: dict[str, Any] = {
            "title": d["title"],
            "description": sanitize_markdown(d["description"]),
            "type": d["type"],
            "notifyMail": int(d["notify_mail"]),
            "audience_intent": d["audience_intent"],
            "published": {"status": 1},
        }
        preview = build_announcement_preview(
            subject=d["title"],
            body_markdown=d["description"],
            channel="email" if d["notify_mail"] else "lms",
            audience_label=d["audience_intent"],
            urgent=d["type"] == "urgent",
        )
        return ProposedAction(
            action="send_announcement",
            target_ref={"audience_intent": d["audience_intent"], "draft_id": parsed.draft_id},
            payload=payload,
            preview=preview,
            content_hash=canonical_hash(payload),
        )
