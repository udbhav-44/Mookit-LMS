"""
GET /v1/meta — instance allowlist + per-tenant limits (A1.7).

Routed at /v1 in main.py.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request

from ..config import settings
from ..contracts.context import RequestContext
from ..core.context import get_request_context

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_EXT_TTL = 300  # seconds


async def _mookit_upload_formats(request: Request, ctx: RequestContext) -> dict | None:
    """Best-effort, Redis-cached fetch of mooKIT's per-entity upload allow-list.

    Lets the UI set a faithful `accept=` for announcement attachments. Never fatal — a miss just
    means the UI falls back to its built-in list.
    """
    redis = getattr(request.app.state, "redis", None)
    mookit = getattr(request.app.state, "mookit_client", None)
    if mookit is None:
        return None
    cache_key = f"{ctx.tenant_key}:allowed_ext"
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("allowed_ext cache read failed: %s", exc)
    try:
        data = await mookit.get_allowed_extensions(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning("allowed_extensions fetch failed: %s", exc)
        return None
    if redis is not None and data:
        try:
            await redis.set(cache_key, json.dumps(data), ex=_ALLOWED_EXT_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("allowed_ext cache write failed: %s", exc)
    return data or None


@router.get("/meta")
async def get_meta(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return per-instance configuration and limit values visible to the UI."""
    # Optionally look up per-instance overrides from the instance registry.
    instance_config: dict = {}
    try:
        from sqlalchemy import select

        from ..store.db import InstanceRegistry
        async with request.app.state.session_factory() as db:
            result = await db.execute(
                select(InstanceRegistry).where(InstanceRegistry.instance_id == ctx.instance_id)
            )
            row = result.scalar_one_or_none()
            if row:
                instance_config = row.config or {}
    except Exception:
        pass  # registry miss is non-fatal

    upload_formats = await _mookit_upload_formats(request, ctx)

    return {
        "instanceId": ctx.instance_id,
        "tenantKey": ctx.tenant_key,
        "courseId": ctx.course_id,
        "userId": ctx.user_id,
        "permissionsOk": bool(ctx.permissions.resources),
        "permissions": ctx.permissions.resources if ctx.permissions.resources else None,
        # Taxonomy (week/module/section) is reachable whenever auth + permissions loaded — the UI
        # uses this to decide whether to populate live dropdowns vs. show a "configure in mooKIT" hint.
        "taxonomyAvailable": bool(ctx.permissions.resources),
        "limits": {
            "maxFileSizeBytes": instance_config.get(
                "max_file_size_bytes", settings.limits.max_file_size_bytes
            ),
            "maxMessagesPerSession": instance_config.get(
                "max_messages_per_session", settings.limits.max_messages_per_session
            ),
            "maxContextTokens": instance_config.get(
                "max_context_tokens", settings.limits.max_context_tokens
            ),
            "rateLimitRpm": instance_config.get(
                "rate_limit_rpm", settings.limits.rate_limit_rpm
            ),
        },
        "allowedFileTypes": [
            ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt",
            ".mp4", ".mov", ".webm", ".mkv", ".m4v",
        ],
        "quizFeatures": {
            "blueprintEnabled": settings.quiz_blueprint_enabled,
            "visionEnabled": settings.quiz_vision_enabled,
        },
        # mooKIT's authoritative per-entity upload allow-list (announcements/lectures/quizzes/...),
        # used by the UI to set a faithful `accept=` for attachments. None when unavailable.
        "mookitUploadFormats": upload_formats,
    }
