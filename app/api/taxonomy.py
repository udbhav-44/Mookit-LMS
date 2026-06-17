"""
GET /v1/taxonomy/{type}   — live course taxonomy terms from mooKIT (week | module | topic | section)
GET /v1/taxonomy          — batch fetch of the common taxonomy types in one round-trip

Backs the instructor-facing dropdowns (week/module/section pickers) so the UI never hardcodes
Week 1–16 or invents section names. Terms come straight from mooKIT `GET /taxonomies/{type}` via
`MooKitClient.list_taxonomy`, cached per tenant in Redis (TTL 300s, matching the permissions cache)
so opening a confirm modal doesn't fan out a request per dropdown.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..contracts.context import RequestContext
from ..core.context import get_request_context

logger = logging.getLogger(__name__)

router = APIRouter()

# mooKIT taxonomy types the UI consumes. `module` maps to mooKIT's topic-style grouping used for
# lectures; `section` is the announcement audience. Kept explicit so an arbitrary type can't be
# proxied straight through to mooKIT.
VALID_TYPES = ("week", "module", "topic", "section")

_TAXONOMY_CACHE_TTL = 300  # seconds — match the permissions cache window


async def _terms_for(request: Request, ctx: RequestContext, type_: str) -> list[dict]:
    """Return [{id, name}] for one taxonomy type, using the Redis cache when available."""
    redis = getattr(request.app.state, "redis", None)
    mookit = getattr(request.app.state, "mookit_client", None)
    if mookit is None:
        raise HTTPException(status_code=503, detail="mooKIT client unavailable.")

    cache_key = f"{ctx.tenant_key}:taxonomy:{type_}"
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                import json
                return json.loads(cached)
        except Exception as exc:  # noqa: BLE001 — cache miss is non-fatal
            logger.warning("Redis taxonomy cache read failed (%s): %s", cache_key, exc)

    terms = await mookit.list_taxonomy(ctx, type_)
    out = [{"id": t.id, "name": t.name} for t in terms]

    if redis is not None:
        try:
            import json
            await redis.set(cache_key, json.dumps(out), ex=_TAXONOMY_CACHE_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis taxonomy cache write failed (%s): %s", cache_key, exc)
    return out


@router.get("/taxonomy/{type}")
async def get_taxonomy(
    type: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the live terms for a single taxonomy type, e.g. {type:'week', terms:[{id,name}]}."""
    if type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown taxonomy type '{type}'. Allowed: {', '.join(VALID_TYPES)}.",
        )
    try:
        terms = await _terms_for(request, ctx, type)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surface mooKIT failures as 502
        logger.warning("Taxonomy fetch failed for type=%s: %s", type, exc)
        raise HTTPException(status_code=502, detail=f"Could not load '{type}' from mooKIT.") from exc
    return {"type": type, "terms": terms}


@router.get("/taxonomy")
async def get_taxonomy_batch(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Batch fetch the common taxonomy types. Per-type failures degrade to an empty list so one
    unconfigured taxonomy doesn't blank the whole modal."""
    result: dict[str, list[dict]] = {}
    for type_ in VALID_TYPES:
        try:
            result[type_] = await _terms_for(request, ctx, type_)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch taxonomy fetch failed for type=%s: %s", type_, exc)
            result[type_] = []
    return result
