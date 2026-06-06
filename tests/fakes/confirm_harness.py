"""UK.4 (part 2) — confirm harness.

Stands in for Dev A's deterministic confirmation gate so Dev B can prove the full
draft -> propose -> confirm -> write path solo. The harness is the ONLY thing that calls mooKIT
writes; a bare ``ProposedAction`` never writes on its own.

It mirrors the real gate's safety property: a write happens only on ``confirm``, and only if the
artifact's current content_hash still matches the one bound at propose time (re-drafting voids it).
"""

from __future__ import annotations

from typing import Any

from app.contracts.mookit import MooKitClient
from app.contracts.types import ProposedAction, RequestContext
from app.core.hashing import canonical_hash

__all__ = ["ConfirmHarness", "PendingAction", "canonical_hash"]


class PendingAction:
    def __init__(self, action_id: str, ctx: RequestContext, proposed: ProposedAction) -> None:
        self.action_id = action_id
        self.ctx = ctx
        self.proposed = proposed
        self.status = "pending"  # pending | confirmed | rejected | stale


class ConfirmHarness:
    """Test-only stand-in for the confirmation gate + deterministic executor."""

    def __init__(self, mookit: MooKitClient) -> None:
        self.mookit = mookit
        self.pending: dict[str, PendingAction] = {}
        self._counter = 0

    def propose(self, ctx: RequestContext, proposed: ProposedAction) -> str:
        """Persist a proposed action; returns an action_id. NEVER writes to mooKIT."""
        self._counter += 1
        action_id = f"act_{self._counter}"
        self.pending[action_id] = PendingAction(action_id, ctx, proposed)
        return action_id

    async def confirm(self, action_id: str, *, current_hash: str | None = None) -> Any:
        """Execute the write via the deterministic executor. Only path that touches mooKIT writes."""
        pa = self.pending[action_id]
        if current_hash is not None and current_hash != pa.proposed.content_hash:
            pa.status = "stale"
            raise ValueError("content_hash mismatch — artifact was edited; token voided")
        result = await self._execute(pa)
        pa.status = "confirmed"
        return result

    def reject(self, action_id: str) -> None:
        self.pending[action_id].status = "rejected"

    async def _execute(self, pa: PendingAction) -> Any:
        """Map ProposedAction -> typed MooKitClient writes. Non-LLM, deterministic."""
        action = pa.proposed.action
        ctx = pa.ctx
        payload = pa.proposed.payload
        target = pa.proposed.target_ref

        if action == "publish_assessment":
            assessment = await self.mookit.create_assessment(
                ctx, target.get("assessment_type", "quizzes"), payload.get("assessment", {})
            )
            for q in payload.get("questions", []):
                await self.mookit.add_question(
                    ctx,
                    target.get("assessment_type", "quizzes"),
                    assessment.id,
                    section_id=payload.get("section_id", 0),
                    body=q,
                )
            return assessment

        if action == "send_announcement":
            return await self.mookit.create_announcement(ctx, payload)

        if action == "publish_lecture":
            file_refs = payload.get("file_ids", [])
            lecture = await self.mookit.create_lecture(ctx, payload.get("lecture", {}))
            if file_refs:
                await self.mookit.attach_course_resource(
                    ctx,
                    "lectures",
                    lecture.id,
                    [
                        {"resourceType": "video", "resourceFileId": fid, "isPrimary": True}
                        for fid in file_refs
                    ],
                )
            return lecture

        raise ValueError(f"unknown action: {action}")
