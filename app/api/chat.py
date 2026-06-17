"""
POST /v1/chat — streaming SSE endpoint (A1.1).

Responsibilities:
  - Enforce per-tenant rate limit before starting the stream.
  - Yield SSE events as described in Contract 6.
  - Detect client disconnect (request.is_disconnected()) and abort cleanly.
  - Create the DB session row inside the generator (not as a dependency — dependency
    sessions close before the long-running stream finishes).
  - Log start + end to the audit trail.
  - Provide an orchestrator seam: if app.state.orchestrator is set (by Dev B), forward
    the chat turn to it; otherwise return a structured stub so the SSE plumbing can be
    tested without the AI brain.

SSE event schema (Contract 6):
  assistant_delta      {"text": "..."}
  tool_started         {"tool": "...", "label": "..."}
  tool_progress        {"tool": "...", "pct": 40, "message": "..."}
  artifact_updated     {"artifact_id": "...", "type": "...", "version": 2}
  pending_confirmation {"action_id": "...", "preview": {...}, "expires_at": "..."}
  clarification        {"preamble": "...", "questions": [{"id","prompt","options","allow_multiple","allow_free_text"}]}
  error                {"code": "...", "message": "...", "retryable": bool}
  done                 {"response_id": "..."}
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..core.rate_limit import check_rate_limit
from ..store.session_repo import persist_message, upsert_session

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None
    instanceId: str | None = None
    references: list[str] = []  # explicit artifact IDs tagged via @ in the UI


@router.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    # Rate-limit check before opening the stream — returns 429 before SSE headers are sent.
    await check_rate_limit(
        request.app.state.redis,
        ctx.tenant_key,
        settings.limits.rate_limit_rpm,
    )

    audit = getattr(request.app.state, "audit_logger", None)
    orchestrator = getattr(request.app.state, "orchestrator", None)
    session_factory = getattr(request.app.state, "session_factory", None)
    ping_interval = settings.limits.sse_ping_interval_seconds

    async def event_generator():
        # Durable transcript is a deliberate dual-write: Redis stays authoritative for the live
        # context window (the orchestrator keeps writing it), and Postgres is the durable record that
        # survives Redis' 24h TTL + a reload and powers the chat-history list. We persist one
        # concatenated assistant message per HTTP turn (a known fidelity trade-off). Every write is
        # best-effort via _safe_persist so a missing/slow DB never aborts the SSE stream.
        assistant_buf: list[str] = []
        try:
            # ── Audit: start (best-effort) ─────────────────────────────────────
            await _safe_audit(audit, ctx, action="chat_start", status="in_progress")

            # ── Durable: create/refresh session row + record the user turn ─────
            await _safe_persist(
                session_factory, "upsert_session",
                lambda: upsert_session(session_factory, ctx, first_user_message=body.message),
            )
            await _safe_persist(
                session_factory, "user_message",
                lambda: persist_message(session_factory, ctx, "user", body.message),
            )

            # ── Main turn: call the orchestrator if wired, else stub ──────────
            if orchestrator is not None:
                # Dev B provides app.state.orchestrator as an async generator that
                # yields SSE event dicts {"event": "...", "data": "..."}.
                async for event in orchestrator.stream(ctx, body.message, references=body.references):
                    if await request.is_disconnected():
                        logger.info("Client disconnected mid-stream: %s", ctx.request_id)
                        return
                    _accumulate_assistant(event, assistant_buf)
                    yield event
            else:
                # Stub turn — used until Dev B wires in the real orchestrator.
                await _send_ping(ping_interval, request)
                stub = _sse("assistant_delta", {"text": "[Orchestrator not yet wired — stub response]"})
                _accumulate_assistant(stub, assistant_buf)
                yield stub
                await asyncio.sleep(0)

            # ── Durable: record the assistant turn + bump updated_at ───────────
            await _safe_persist(
                session_factory, "assistant_message",
                lambda: persist_message(session_factory, ctx, "assistant", "".join(assistant_buf)),
            )
            await _safe_persist(
                session_factory, "touch_session",
                lambda: upsert_session(session_factory, ctx),
            )

            # ── Done ──────────────────────────────────────────────────────────
            await _safe_audit(audit, ctx, action="chat_end", status="success")

            yield _sse("done", {"response_id": ctx.request_id})

        except asyncio.CancelledError:
            logger.info("Chat stream cancelled: %s", ctx.request_id)
            await _safe_audit(audit, ctx, action="chat_end", status="cancelled")
            raise

        except Exception as exc:
            logger.exception("Unhandled error in chat stream %s", ctx.request_id)
            await _safe_audit(audit, ctx, action="chat_end", status="error")
            yield _sse("error", {
                "code": "internal_error",
                "message": str(exc),
                "retryable": False,
            })

    return EventSourceResponse(
        event_generator(),
        ping=int(ping_interval),      # heartbeat keeps SSE alive through proxies
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


async def _safe_audit(audit: Any, ctx: RequestContext, **kwargs: Any) -> None:
    """Write audit row without letting failures abort the SSE stream."""
    if audit is None:
        return
    try:
        await audit.log(ctx, **kwargs)
    except Exception as exc:
        logger.warning("Audit log skipped: %s", exc)


async def _safe_persist(session_factory: Any, label: str, make_coro: Any) -> None:
    """Run a durable-history write best-effort: a missing/slow DB must never abort the SSE stream."""
    if session_factory is None:
        return
    try:
        await make_coro()
    except Exception as exc:
        logger.warning("Durable %s skipped: %s", label, exc)


def _accumulate_assistant(event: dict, buf: list[str]) -> None:
    """Capture assistant text from the same assistant_delta events the client renders (no drift)."""
    if event.get("event") != "assistant_delta":
        return
    try:
        text = json.loads(event.get("data") or "{}").get("text")
    except (ValueError, TypeError):
        return
    if text:
        buf.append(text)


async def _send_ping(interval: float, request: Request) -> None:
    """Yield nothing but wait a tick so the connection stays open."""
    await asyncio.sleep(0)


def build_pending_confirmation_event(
    action_id: str, confirm_token: str, preview: dict
) -> dict:
    """Helper for the orchestrator / confirmation gate to emit the SSE event."""
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=settings.security.confirm_token_ttl_seconds)
    ).isoformat()
    return _sse("pending_confirmation", {
        "action_id": action_id,
        "confirm_token": confirm_token,
        "preview": preview,
        "expires_at": expires_at,
    })
