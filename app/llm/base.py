"""Re-export the LLMProvider ABC from contracts for ergonomic imports under app.llm."""

from app.contracts.types import LLMProvider

__all__ = ["LLMProvider"]
