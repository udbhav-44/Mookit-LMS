"""POST /v1/lecture/{draft_id}/edit — adjust a lecture draft's week/module/schedule before publish.

Lets the instructor change the resolved week (and optional module) of a lecture_draft without
re-prompting the model. Week/module labels are re-resolved against the LIVE mooKIT taxonomy here
(server-side) so the stored draft always carries real integer ids — never an unresolved label that
would fail at publish time.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..gen.lecture_meta import draft_lecture_meta
from ..gen.provenance import mark_edited

logger = logging.getLogger(__name__)

router = APIRouter()


class LectureEditBody(BaseModel):
    week_label: str | None = None
    module_label: str | None = None
    release_on: int | None = None        # unix seconds; null => publish now
    clear_schedule: bool = False         # explicitly drop a previously-set release_on


@router.post("/lecture/{draft_id}/edit")
async def edit_lecture(
    draft_id: str,
    body: LectureEditBody,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    if not ctx.permissions.has_permission("lectures", "create"):
        raise HTTPException(status_code=403, detail="Missing lectures:create permission.")

    registry = request.app.state.artifact_registry
    art = await registry.get(ctx, draft_id)
    if art is None or art.type != "lecture_draft":
        raise HTTPException(status_code=404, detail="Lecture draft not found.")

    payload = dict(art.payload)
    week_label = body.week_label or payload.get("week_label")
    if not week_label:
        raise HTTPException(status_code=400, detail="A week is required.")
    module_label = body.module_label if body.module_label is not None else payload.get("module_label")
    release_on = None if body.clear_schedule else (body.release_on if body.release_on is not None else payload.get("release_on"))

    mookit = getattr(request.app.state, "mookit_client", None)
    if mookit is None:
        raise HTTPException(status_code=503, detail="mooKIT client unavailable.")

    meta = await draft_lecture_meta(
        mookit, ctx,
        week_label=week_label,
        module_label=module_label,
        file_artifact_id=payload.get("file_artifact_id"),
        release_on=release_on,
    )
    if meta.ambiguous or meta.week_id is None:
        available = ", ".join(c.get("title", "") for c in meta.candidates) or "(none)"
        raise HTTPException(
            status_code=400,
            detail=f"Couldn't match week '{week_label}'. Available weeks: {available}.",
        )

    # Preserve fields the meta refresh doesn't own (uploaded file ids, generated title).
    new_payload = meta.model_dump()
    new_payload["title"] = payload.get("title", meta.title)
    new_payload["file_mookit_id"] = payload.get("file_mookit_id")

    updated = await registry.update(
        ctx, draft_id,
        {"title": new_payload["title"], "payload": new_payload,
         "provenance": mark_edited(art.provenance)},
    )
    return {
        "success": True,
        "artifact_id": updated.id,
        "version": updated.version,
        "payload": updated.payload,
    }
