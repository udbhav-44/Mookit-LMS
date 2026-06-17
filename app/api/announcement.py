"""POST /v1/announcement/{draft_id}/edit — deterministic announcement draft edits for the demo UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import settings
from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..gen.provenance import mark_edited
from ..preview.render import sanitize_markdown

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/announcement/attach")
async def attach_announcement_file(
    request: Request,
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(get_request_context),
):
    """Upload one attachment for an announcement to mooKIT and return its managed file id.

    Staged with ``entityType=announcements`` / ``entityId=0`` (announcements accept the file before
    the announcement exists; mooKIT links them on send via ``fileIds``). mooKIT enforces the
    per-entity format allow-list, so we forward the bytes and surface its rejection rather than
    duplicating the list here.
    """
    if not ctx.permissions.has_permission("announcements", "create"):
        raise HTTPException(status_code=403, detail="Missing announcements:create permission.")

    content = await file.read()
    max_bytes = settings.limits.max_file_size_bytes
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content)} bytes (max {max_bytes} bytes).",
        )

    filename = file.filename or "attachment"
    mookit = getattr(request.app.state, "mookit_client", None)
    if mookit is None:
        raise HTTPException(status_code=503, detail="mooKIT client unavailable.")

    try:
        managed = await mookit.upload_file(
            ctx,
            {"files": (filename, content, file.content_type or "application/octet-stream")},
            entity_type="announcements",
            entity_id=0,
        )
    except Exception as exc:  # noqa: BLE001 — surface mooKIT's own validation message
        logger.warning("Announcement attachment upload failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Attachment upload failed: {exc}") from exc

    if not managed:
        raise HTTPException(status_code=502, detail="mooKIT returned no file for the attachment.")
    return {"success": True, "fileId": managed[0].id, "filename": filename}


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
