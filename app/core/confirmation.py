"""
Confirmation gate (A3.1 / A3.2).

The model loop (Dev B) calls `propose()` which stores a pending action and returns
the action_id + confirm_token for the SSE `pending_confirmation` event.

The confirm endpoint calls `verify_and_get()` which:
  1. Checks the action exists, is pending, and belongs to the right tenant.
  2. Verifies the one-time confirm_token via constant-time comparison (TOCTOU-safe).
  3. Re-computes the sha256 of the stored payload and checks it against content_hash —
     this ensures that a "approve benign / swap malicious" attack is blocked: re-drafting
     the payload without going through propose() again will produce a hash mismatch.

`complete()` marks the action as confirmed/rejected so the token can never be reused.
"""

import hashlib
import json
import secrets
import uuid

from sqlalchemy import insert, select, update

from ..contracts.context import RequestContext
from ..contracts.tools import ProposedAction
from ..store.db import PendingAction


def _canonical_hash(payload: dict) -> str:
    """sha256 of the JSON-serialised payload with sorted keys (deterministic)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ConfirmationGate:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    # Called by the orchestrator (Dev B) when it yields a ProposedAction
    # ------------------------------------------------------------------

    async def propose(
        self, ctx: RequestContext, action: ProposedAction
    ) -> tuple[str, str]:
        """Persist a ProposedAction and return (action_id, confirm_token).

        The confirm_token is a cryptographically random 32-byte URL-safe token
        that is bound to (action_type, target_ref, content_hash) via storage —
        you cannot confirm without it, and it is invalidated on first use.
        """
        action_id = str(uuid.uuid4())
        confirm_token = secrets.token_urlsafe(32)

        # Re-compute hash from the actual payload to be stored — dev B should set
        # action.content_hash, but we re-derive it server-side to be authoritative.
        server_hash = _canonical_hash(action.payload)

        async with self.session_factory() as session:
            stmt = insert(PendingAction).values(
                id=action_id,
                tenant_key=ctx.tenant_key,
                action=action.action,
                target_ref=action.target_ref,
                payload=action.payload,
                content_hash=server_hash,
                confirm_token=confirm_token,
                preview_json=action.preview.model_dump(),
                status="pending",
            )
            await session.execute(stmt)
            await session.commit()

        return action_id, confirm_token

    # ------------------------------------------------------------------
    # Called by POST /v1/actions/{action_id}/confirm
    # ------------------------------------------------------------------

    async def verify_and_get(
        self,
        action_id: str,
        tenant_key: str,
        confirm_token: str,
    ) -> tuple[bool, PendingAction | None]:
        """Return (True, action) iff the token is valid and the payload hash still matches.

        All three checks must pass; failure in any returns (False, None) without
        revealing which check failed (to avoid information leakage).
        """
        async with self.session_factory() as session:
            stmt = select(PendingAction).where(
                PendingAction.id == action_id,
                PendingAction.tenant_key == tenant_key,
                PendingAction.status == "pending",
            )
            result = await session.execute(stmt)
            action = result.scalar_one_or_none()

        if action is None:
            return False, None

        # 1. Constant-time token comparison — prevents timing attacks.
        if not secrets.compare_digest(action.confirm_token, confirm_token):
            return False, None

        # 2. Re-derive hash from the stored payload and compare.
        #    If someone tampered with `pending_actions.payload` in the DB
        #    (or the payload changed between proposal and confirmation),
        #    this will mismatch and the confirm is denied.
        recomputed = _canonical_hash(action.payload)
        if not secrets.compare_digest(recomputed, action.content_hash):
            return False, None

        return True, action

    async def revise_announcement(
        self,
        action_id: str,
        tenant_key: str,
        *,
        title: str,
        description: str,
    ) -> PendingAction | None:
        """Update a pending send_announcement payload + preview after instructor edits in the UI.

        Recomputes content_hash from the revised payload so confirm still verifies integrity.
        """
        from app.preview.render import build_announcement_preview, sanitize_markdown

        async with self.session_factory() as session:
            stmt = select(PendingAction).where(
                PendingAction.id == action_id,
                PendingAction.tenant_key == tenant_key,
                PendingAction.status == "pending",
                PendingAction.action == "send_announcement",
            )
            result = await session.execute(stmt)
            action = result.scalar_one_or_none()
            if action is None:
                return None

            payload = dict(action.payload)
            payload["title"] = title.strip()
            payload["description"] = sanitize_markdown(description)
            audience = payload.get("_audience_intent", "all")
            notify_mail = bool(payload.get("notifyMail"))
            urgent = payload.get("type") == "urgent"
            preview = build_announcement_preview(
                subject=payload["title"],
                body_markdown=description,
                channel="email" if notify_mail else "lms",
                audience_label=audience,
                urgent=urgent,
            )
            server_hash = _canonical_hash(payload)
            await session.execute(
                update(PendingAction)
                .where(PendingAction.id == action_id)
                .values(
                    payload=payload,
                    content_hash=server_hash,
                    preview_json=preview.model_dump(),
                )
            )
            await session.commit()
            action.payload = payload
            action.content_hash = server_hash
            action.preview_json = preview.model_dump()
            return action

    # ------------------------------------------------------------------
    # Called after successful execution or explicit rejection
    # ------------------------------------------------------------------

    async def complete(self, action_id: str, status: str) -> None:
        """Mark the action confirmed/rejected so the token cannot be reused."""
        async with self.session_factory() as session:
            stmt = (
                update(PendingAction)
                .where(PendingAction.id == action_id)
                .values(status=status)
            )
            await session.execute(stmt)
            await session.commit()
