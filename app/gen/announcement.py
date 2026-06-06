"""B3.2 — announcement draft generation.

Produces title (subject) + description (body), infers type (normal/urgent) and notifyMail (email vs
LMS-only), and an AUDIENCE INTENT label (e.g. "all", "Section 3"). It never emits resolved recipient
ids — the model/document can never name a recipient; the gate resolves targets server-side.

The LLM draft step is an injected seam; a deterministic default keeps it testable offline.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

URGENT_HINTS = ("cancel", "urgent", "emergency", "immediately", "asap", "rescheduled")
EMAIL_HINTS = ("email", "e-mail", "mail")


class AnnouncementDraft(BaseModel):
    title: str
    description: str
    type: str  # "normal" | "urgent"
    notify_mail: bool  # True => email channel, False => LMS-only
    audience_intent: str  # label only, e.g. "all", "Section 3" — NEVER resolved ids


class DraftFn(Protocol):
    async def __call__(self, *, intent: str, audience_intent: str) -> AnnouncementDraft: ...


async def draft_announcement(
    *, intent: str, audience_intent: str = "all", generator: DraftFn | None = None
) -> AnnouncementDraft:
    if generator is not None:
        return await generator(intent=intent, audience_intent=audience_intent)
    return _default_draft(intent=intent, audience_intent=audience_intent)


def _default_draft(*, intent: str, audience_intent: str) -> AnnouncementDraft:
    low = intent.lower()
    urgent = any(h in low for h in URGENT_HINTS)
    notify_mail = any(h in low for h in EMAIL_HINTS) or urgent
    subject = _subject_from(intent)
    return AnnouncementDraft(
        title=subject,
        description=intent.strip().rstrip(".") + ".",
        type="urgent" if urgent else "normal",
        notify_mail=notify_mail,
        audience_intent=audience_intent,
    )


def _subject_from(intent: str) -> str:
    words = intent.strip().split()
    head = " ".join(words[:8])
    return head[:1].upper() + head[1:] if head else "Announcement"
