"""OpenAI-backed announcement draft generator — production seam for DraftAnnouncementTool."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.contracts import LLMProvider
from app.core.prompts.system import SYSTEM_PROMPT
from app.gen.announcement import AnnouncementDraft, _default_draft

_ANNOUNCEMENT_INSTRUCTIONS = """\
You write course announcements for university instructors on an LMS (mooKIT).

Given the instructor's intent and audience label, produce:
- title: a concise email/LMS subject line (≤ 90 characters), professional tone.
- description: the full announcement body (2–5 sentences) students will read. Include:
    • what happened / what is changing
    • any action students should take (if applicable)
    • a brief professional sign-off line (e.g. "Thank you, [Course Team]")

Rules:
- Do NOT include URLs, phone numbers, or email addresses.
- Do NOT name specific students or resolve audience to ids — audience is metadata only.
- Write in clear, direct instructor voice.
"""


class GenAnnouncementContent(BaseModel):
    title: str = Field(description="Announcement subject line shown to students")
    description: str = Field(description="Full announcement body text")


class OpenAIAnnouncementGenerator:
    def __init__(self, provider: LLMProvider, *, temperature: float = 0.7) -> None:
        self._provider = provider
        self._temperature = temperature

    async def __call__(self, *, intent: str, audience_intent: str) -> AnnouncementDraft:
        prompt = (
            f"Instructor intent: {intent.strip()}\n"
            f"Audience label (intent only, do not resolve): {audience_intent}\n"
        )
        try:
            gen = await self._provider.respond_structured(
                instructions=SYSTEM_PROMPT + "\n\n" + _ANNOUNCEMENT_INSTRUCTIONS,
                input=[{"role": "user", "content": prompt}],
                schema=GenAnnouncementContent,
                temperature=self._temperature,
            )
            base = _default_draft(intent=intent, audience_intent=audience_intent)
            return base.model_copy(
                update={
                    "title": gen.title.strip()[:200] or base.title,
                    "description": gen.description.strip() or base.description,
                }
            )
        except Exception:
            return _default_draft(intent=intent, audience_intent=audience_intent)
