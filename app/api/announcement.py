"""POST /v1/announcement/{draft_id}/edit — deterministic announcement draft edits for the demo UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..gen.provenance import mark_edited
from ..preview.render import sanitize_markdown

logger = logging.getLogger(__name__)

router = APIRouter()


class AnnouncementEditBody(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)


@router.post("/announcement/{draft_id}/edit")
async def edit_announcement(
    draft_id: str,
    body: AnnouncementEditBody,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    if not ctx.permissions.has_permission("announcements", "create"):
        raise HTTPException(status_code=403, detail="Missing announcements:create permission.")

    if body.title is None and body.description is None:
        raise HTTPException(status_code=400, detail="Provide title and/or description to edit.")

    registry = request.app.state.artifact_registry
    art = await registry.get(ctx, draft_id)
    if art is None or art.type != "announcement_draft":
        raise HTTPException(status_code=404, detail="Announcement draft not found.")

    payload = dict(art.payload)
    if body.title is not None:
        payload["title"] = body.title.strip()
    if body.description is not None:
        payload["description"] = sanitize_markdown(body.description)

    updated = await registry.update(
        ctx,
        draft_id,
        {
            "title": payload["title"],
            "payload": payload,
            "provenance": mark_edited(art.provenance),
        },
    )
    return {
        "success": True,
        "artifact_id": updated.id,
        "version": updated.version,
        "title": updated.title,
        "payload": updated.payload,
        "provenance": updated.provenance,
    }
