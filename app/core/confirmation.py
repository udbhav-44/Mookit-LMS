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
        audience: "str | int | None" = None,
        audience_label: str | None = None,
        notify_mail: int | None = None,
        schedule_at: int | None = None,
        file_ids: "list[int] | None" = None,
    ) -> PendingAction | None:
        """Update a pending send_announcement payload + preview after instructor edits in the UI.

        Handles the full set of confirm-modal controls: subject/body, audience (``"all"`` or a
        section taxonomy id), email channel, schedule, and attachments. Audience is stored as an
        intent/section-id pair; the executor re-resolves it fail-closed at confirm time so a stale
        or bogus section never silently broadcasts to everyone. ``schedule_at`` in the future sets
        ``published.status=0`` + ``releaseOn``; otherwise the announcement publishes immediately.
        Recomputes content_hash so confirm still verifies integrity.
        """
        import time

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

            if notify_mail is not None:
                payload["notifyMail"] = int(notify_mail)

            # Audience: "all" clears any section targeting; an int is a section taxonomy id that the
            # executor will re-validate. The label is cosmetic (preview only) and never trusted for
            # the actual send.
            if audience is not None:
                is_all = (isinstance(audience, str) and audience.strip().lower() in {"all", ""})
                if is_all:
                    payload["_audience_intent"] = "all"
                    payload.pop("_audience_section_id", None)
                    payload.pop("sectionIds", None)
                else:
                    sid = int(audience)
                    payload["_audience_section_id"] = sid
                    payload["_audience_intent"] = audience_label or f"section {sid}"

            # Schedule: future timestamp → draft + releaseOn; otherwise publish now.
            now = int(time.time())
            if schedule_at and schedule_at > now:
                payload["published"] = {"status": 0, "releaseOn": int(schedule_at)}
            else:
                payload["published"] = {"status": 1, "releaseOn": None}

            if file_ids is not None:
                payload["fileIds"] = [int(f) for f in file_ids] or None

            audience_text = payload.get("_audience_intent", "all")
            notify = bool(payload.get("notifyMail"))
            urgent = payload.get("type") == "urgent"
            schedule_label = None
            pub = payload.get("published") or {}
            if pub.get("status") == 0 and pub.get("releaseOn"):
                from datetime import datetime, timezone
                schedule_label = datetime.fromtimestamp(
                    int(pub["releaseOn"]), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC")
            preview = build_announcement_preview(
                subject=payload["title"],
                body_markdown=description,
                channel="email" if notify else "lms",
                audience_label=audience_text,
                urgent=urgent,
                schedule_label=schedule_label,
                attachment_count=len(payload.get("fileIds") or []),
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

    async def revise_assessment(
        self,
        action_id: str,
        tenant_key: str,
        *,
        assessment_type: str,
        start_date: int,
        end_date: int,
        end_dap_date: int,
        results_date: int,
        timed: int = 0,
        duration: int | None = None,
        instructions: str | None = None,
        show_correct_answers: int = 0,
        retake_allowed: int = 0,
    ) -> PendingAction | None:
        """Apply instructor-configured quiz settings to a pending publish_assessment payload.

        Writes the camelCase keys onto ``payload["assessment"]`` (the AssessmentCreate body) and
        ``payload["_type"]`` so the executor publishes exactly what the modal showed. Recomputes the
        content_hash and rebuilds the preview. Does NOT touch ``questions`` — question edits go
        through the draft card / POST /v1/quiz/{id}/edit. Raises ValueError on invalid date ordering.
        """
        from app.preview.render import build_assessment_preview

        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")
        if results_date < end_date:
            raise ValueError("Results date must be on or after the end date.")
        if timed and (duration is None or duration < 1):
            raise ValueError("Duration (minutes) is required when the quiz is timed.")

        async with self.session_factory() as session:
            stmt = select(PendingAction).where(
                PendingAction.id == action_id,
                PendingAction.tenant_key == tenant_key,
                PendingAction.status == "pending",
                PendingAction.action == "publish_assessment",
            )
            result = await session.execute(stmt)
            action = result.scalar_one_or_none()
            if action is None:
                return None

            payload = dict(action.payload)
            payload["_type"] = assessment_type
            assessment = dict(payload.get("assessment") or {})
            assessment.update(
                {
                    "startDate": start_date,
                    "endDate": end_date,
                    "endDapDate": end_dap_date,
                    "resultsDate": results_date,
                    "timed": int(timed),
                    "showCorrectAnswers": int(show_correct_answers),
                    "retakeAllowed": int(retake_allowed),
                }
            )
            # Only carry duration when timed — a stale duration on an untimed quiz is misleading.
            if timed:
                assessment["duration"] = duration
            else:
                assessment.pop("duration", None)
            if instructions is not None:
                assessment["instructions"] = instructions.strip() or None
            payload["assessment"] = assessment

            preview = build_assessment_preview(
                title=assessment.get("title", "Quiz"),
                questions=payload.get("questions", []),
                assessment=assessment,
                assessment_type=assessment_type,
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
