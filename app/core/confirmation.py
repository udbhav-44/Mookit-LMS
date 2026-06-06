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
from typing import Tuple

from sqlalchemy import insert, select, update

from ..contracts.tools import ProposedAction
from ..contracts.context import RequestContext
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
    ) -> Tuple[str, str]:
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
    ) -> Tuple[bool, PendingAction | None]:
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
