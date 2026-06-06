"""Test-only confirmation harness.

Stands in for the DB-backed ConfirmationGate so Dev B flow tests can prove the full
draft → propose → confirm → write path offline. Execution delegates to the REAL Dev A
``DeterministicExecutor`` (not a reimplementation), so these tests exercise the actual write mapping.

Mirrors the gate's safety property: a write happens only on ``confirm`` and only if the artifact's
current content_hash still matches the one bound at propose time (re-drafting voids it).
"""

from __future__ import annotations

from typing import Any

from app.contracts.context import RequestContext
from app.contracts.mookit import MooKitClient
from app.contracts.tools import ProposedAction
from app.core.executor import DeterministicExecutor
from app.core.hashing import canonical_hash

__all__ = ["ConfirmHarness", "PendingAction", "canonical_hash"]


class PendingAction:
    def __init__(self, action_id: str, ctx: RequestContext, proposed: ProposedAction) -> None:
        self.action_id = action_id
        self.ctx = ctx
        self.proposed = proposed
        self.status = "pending"  # pending | confirmed | rejected | stale


class ConfirmHarness:
    def __init__(self, mookit: MooKitClient) -> None:
        self.mookit = mookit
        self.executor = DeterministicExecutor(mookit)
        self.pending: dict[str, PendingAction] = {}
        self._counter = 0

    def propose(self, ctx: RequestContext, proposed: ProposedAction) -> str:
        """Persist a proposed action; returns an action_id. NEVER writes to mooKIT."""
        self._counter += 1
        action_id = f"act_{self._counter}"
        self.pending[action_id] = PendingAction(action_id, ctx, proposed)
        return action_id

    async def confirm(self, action_id: str, *, current_hash: str | None = None) -> Any:
        """Execute via the deterministic executor — the only path that touches mooKIT writes."""
        pa = self.pending[action_id]
        if current_hash is not None and current_hash != pa.proposed.content_hash:
            pa.status = "stale"
            raise ValueError("content_hash mismatch — artifact was edited; token voided")
        result = await self.executor.execute(pa.ctx, pa.proposed.action, dict(pa.proposed.payload))
        pa.status = "confirmed"
        return result

    def reject(self, action_id: str) -> None:
        self.pending[action_id].status = "rejected"
