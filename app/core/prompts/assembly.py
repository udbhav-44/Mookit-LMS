"""B0.3 — prompt-cache-disciplined input assembly.

Ordering rule (static-first, for prompt caching): the system prompt + tool schemas form a byte-stable
prefix that NEVER changes between turns; variable content (artifact manifest, transcript, user turn)
always comes AFTER it. We set ``prompt_cache_key`` per (tenant_key, model, PROMPT_VERSION).

Note: with the Responses API the system prompt is passed via the ``instructions`` argument and tool
schemas via ``tools`` (both cached by the SDK as the stable prefix). ``build_input`` assembles only the
``input`` list (manifest → transcript → user turn), keeping variable content last and ordered.
"""

from __future__ import annotations

from typing import Any

from app.config import PROMPT_VERSION
from app.contracts import Message


def prompt_cache_key(*, tenant_key: str, model: str) -> str:
    return f"{tenant_key}:{model}:v{PROMPT_VERSION}"


def _message_dict(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": text}


def build_input(
    *,
    manifest: str | None,
    transcript: list[Message],
    user_turn: str,
    references_block: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble the Responses ``input`` list with variable content ordered manifest → references →
    transcript → user.

    The system prompt and tool schemas are supplied separately (instructions/tools) as the stable
    cache prefix and are intentionally NOT part of this list. ``references_block`` holds the artifacts
    the instructor explicitly @-tagged this turn and sits right after the read-only manifest so it
    outranks the transcript and user turn in the instruction hierarchy.
    """
    items: list[dict[str, Any]] = []
    if manifest:
        # Injected as a developer message so it sits above the user turn in the instruction hierarchy.
        items.append(_message_dict("developer", f"CURRENT ARTIFACTS (read-only context):\n{manifest}"))
    if references_block:
        items.append(_message_dict("developer", references_block))
    for msg in transcript:
        role = msg.role if msg.role in {"user", "assistant", "developer", "system"} else "user"
        items.append(_message_dict(role, msg.content))
    items.append(_message_dict("user", user_turn))
    return items
