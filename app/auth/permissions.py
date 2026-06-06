from fastapi import HTTPException

from ..contracts.context import RequestContext

# Maps a confirm action name to the (resource, action) pair that the user must hold.
# This is the server-side authoritative mapping — never derived from model output.
ACTION_PERMISSION_MAP: dict[str, tuple[str, str]] = {
    "create_assessment":   ("assessments", "create"),
    "update_assessment":   ("assessments", "update"),
    "publish_assessment":  ("assessments", "update"),
    "add_question":        ("assessments", "update"),
    "create_announcement": ("announcements", "create"),
    "send_announcement":   ("announcements", "create"),
    "create_lecture":      ("lectures", "create"),
    "publish_lecture":     ("lectures", "update"),
    "upload_file":         ("files", "upload"),
}


def require_permission(ctx: RequestContext, resource: str, action: str) -> None:
    """Raise HTTP 403 if the current user lacks `action` on `resource`.

    Used by the confirmation gate and tool dispatch — never by the model itself.
    """
    if not ctx.permissions.has_permission(resource, action):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: '{action}' on '{resource}' for user {ctx.user_id}",
        )


def require_action_permission(ctx: RequestContext, action_name: str) -> None:
    """Look up the required permission for a pending-action type and enforce it.

    Called on /confirm to re-validate that the user still holds the permission
    at execution time, not just at proposal time.
    """
    mapping = ACTION_PERMISSION_MAP.get(action_name)
    if mapping is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action type: '{action_name}'",
        )
    resource, action = mapping
    require_permission(ctx, resource, action)
