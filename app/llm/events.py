"""LLM provider exceptions.

Typed event classes were removed in the Dev A/Dev B integration: the canonical contract uses a
generic ``LLMEvent(event_type, data)`` (see app/contracts/llm.py). These exceptions are still raised by
``respond_structured`` to make refusals and length-truncation explicit.
"""

from __future__ import annotations


class ModelRefusal(Exception):
    """Raised by respond_structured when the model returns a refusal."""

    def __init__(self, refusal: str) -> None:
        super().__init__(f"model refused: {refusal}")
        self.refusal = refusal


class OutputTruncated(Exception):
    """Raised when a structured response is cut off by the length limit."""

    def __init__(self, detail: str = "output truncated by length limit") -> None:
        super().__init__(detail)
