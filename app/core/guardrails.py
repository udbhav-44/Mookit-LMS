"""B4.2 — guardrails integration at the model boundary.

Thin adapter over Dev A's guardrail hooks (injection/jailbreak + moderation). Solo, it ships a
heuristic shim that flags obvious injection/jailbreak patterns so the screening PATH is exercised and
tested; in integration the real OpenAI Guardrails + Moderation hooks are injected.

Screening runs on uploaded text and tool outputs BEFORE they enter the model context. Structured
outputs (P2) already shrink the injection surface.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel

_INJECTION_PATTERNS = [
    r"ignore\s+(all|any|previous|prior|the)?[\w\s]{0,30}?(instructions|rules)",
    r"disregard (the )?(above|previous|system)",
    r"you are now (in )?(admin|developer|jailbreak|dan) mode",
    r"reveal (the )?(system )?prompt",
    r"\bpublish (this|it|the quiz|now)\b.*\bwithout\b",
    r"do not ask for confirmation",
    r"email .* to .*@",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


class GuardrailResult(BaseModel):
    allowed: bool
    flags: list[str]

    @property
    def blocked(self) -> bool:
        return not self.allowed


class GuardrailHook(Protocol):
    async def __call__(self, text: str) -> GuardrailResult: ...


def _heuristic_screen(text: str) -> GuardrailResult:
    flags = [p.pattern for p in _COMPILED if p.search(text)]
    # We FLAG but do not hard-block by default: the architecture (gate) is the real backstop, and
    # over-blocking legitimate content hurts UX. Dev A's real hook decides blocking policy.
    return GuardrailResult(allowed=True, flags=flags)


async def screen_input(text: str, *, hook: GuardrailHook | None = None) -> GuardrailResult:
    if hook is not None:
        return await hook(text)
    return _heuristic_screen(text)


async def screen_tool_output(text: str, *, hook: GuardrailHook | None = None) -> GuardrailResult:
    if hook is not None:
        return await hook(text)
    return _heuristic_screen(text)
