"""B0.2 — LLM event types + typed exceptions.

Re-exports the LLMEvent union from contracts and adds provider-level exceptions.
"""

from __future__ import annotations

from app.contracts.types import (
    AssistantDelta,
    ErrorEvent,
    LLMEvent,
    ResponseCompleted,
    ToolCallArgsDelta,
    ToolCallArgsDone,
    ToolCallStarted,
)

__all__ = [
    "AssistantDelta",
    "ErrorEvent",
    "LLMEvent",
    "ModelRefusal",
    "OutputTruncated",
    "ResponseCompleted",
    "ToolCallArgsDelta",
    "ToolCallArgsDone",
    "ToolCallStarted",
]


class ModelRefusal(Exception):
    """Raised by respond_structured when the model returns a refusal."""

    def __init__(self, refusal: str) -> None:
        super().__init__(f"model refused: {refusal}")
        self.refusal = refusal


class OutputTruncated(Exception):
    """Raised when a structured response is cut off by the length limit."""

    def __init__(self, detail: str = "output truncated by length limit") -> None:
        super().__init__(detail)
