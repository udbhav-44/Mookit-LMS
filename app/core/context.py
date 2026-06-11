import contextvars
import logging
import uuid

from fastapi import HTTPException, Request

from ..contracts.context import PermissionMatrix, RequestContext

logger = logging.getLogger(__name__)

# Thread-local context var so middleware can inject and any coroutine can read it.
request_context_var: contextvars.ContextVar[RequestContext] = contextvars.ContextVar("request_context")

_PERM_CACHE_TTL = 300  # 5 minutes — short enough to pick up permission revocations


async def get_request_context(request: Request) -> RequestContext:
    """FastAPI dependency that builds a fully-populated RequestContext.

    Steps (per A1.2):
    1. Parse required auth headers: course, token, uid.
    2. Parse body fields: instanceId, sessionId.
    3. Derive tenant_key = "{instance_id}:{course_id}".
    4. Mint a request_id UUID.
    5. Fetch (or restore from Redis cache) the PermissionMatrix for this user/course.
    6. Store the context in a ContextVar for structured-log injection.
    """
    course = request.headers.get("course") or request.headers.get("x-course")
    token = request.headers.get("token") or request.headers.get("x-token")
    uid_raw = request.headers.get("uid") or request.headers.get("x-user-id")
    role = request.headers.get("role", "instructor")

    if not course or not token or not uid_raw:
        raise HTTPException(
            status_code=401,
            detail="Missing required auth headers: course, token, uid",
        )

    try:
        user_id = int(uid_raw)
    except ValueError as err:
        raise HTTPException(status_code=401, detail="Invalid uid header: must be an integer") from err

    # Body is optional — some endpoints (e.g. file upload) don't have a JSON body.
    try:
        body = await request.json()
    except Exception:
        body = {}

    instance_id: str = body.get("instanceId") or request.headers.get("x-instance-id", "default")
    session_id: str = (
        body.get("sessionId")
        or request.headers.get("x-session-id")
        or request.headers.get("session")
        or str(uuid.uuid4())
    )
    tenant_key = f"{instance_id}:{course}"
    request_id = str(uuid.uuid4())

    forwarded_headers = {"course": course, "token": token, "uid": uid_raw}

    # Build a minimal context so we can call the mooKIT client.
    minimal_ctx = RequestContext(
        instance_id=instance_id,
        course_id=course,
        user_id=user_id,
        role=role,
        session_id=session_id,
        forwarded_headers=forwarded_headers,
        permissions=PermissionMatrix(resources={}),
        tenant_key=tenant_key,
        request_id=request_id,
    )

    permissions = await _fetch_permissions(request, minimal_ctx, tenant_key)

    ctx = minimal_ctx.model_copy(update={"permissions": permissions})
    request_context_var.set(ctx)
    return ctx


async def _fetch_permissions(
    request: Request, ctx: RequestContext, tenant_key: str
) -> PermissionMatrix:
    """Return permissions from Redis cache, or fetch from mooKIT and cache the result."""
    redis = getattr(request.app.state, "redis", None)
    mookit = getattr(request.app.state, "mookit_client", None)

    if redis is None or mookit is None:
        # During startup / tests without full app state, fall back to empty matrix.
        logger.warning("app.state not fully initialised; using empty PermissionMatrix")
        return PermissionMatrix(resources={})

    cache_key = f"{tenant_key}:perms"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return PermissionMatrix.model_validate_json(cached)
    except Exception as exc:
        logger.warning("Redis permissions cache read failed: %s", exc)

    try:
        permissions = await mookit.get_permissions(ctx)
        try:
            await redis.set(cache_key, permissions.model_dump_json(), ex=_PERM_CACHE_TTL)
        except Exception as exc:
            logger.warning("Redis permissions cache write failed: %s", exc)
        return permissions
    except Exception as exc:
        logger.error("Failed to fetch permissions from mooKIT: %s", exc)
        # Fail-closed: return empty permissions so all require_permission checks deny.
        return PermissionMatrix(resources={})
