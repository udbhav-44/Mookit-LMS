"""
GET /v1/meta — instance allowlist + per-tenant limits (A1.7).

Routed at /v1 in main.py.
"""

from fastapi import APIRouter, Depends, Request

from ..config import settings
from ..contracts.context import RequestContext
from ..core.context import get_request_context

router = APIRouter()


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

    return {
        "instanceId": ctx.instance_id,
        "tenantKey": ctx.tenant_key,
        "courseId": ctx.course_id,
        "userId": ctx.user_id,
        "permissionsOk": bool(ctx.permissions.resources),
        "permissions": ctx.permissions.resources if ctx.permissions.resources else None,
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
    }
