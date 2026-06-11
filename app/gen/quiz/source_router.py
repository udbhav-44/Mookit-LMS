"""Phase 1 — adaptive source routing for quiz comprehension.

Documents vary from a single page to whole libraries, so the comprehension stage adapts to size
rather than always retrieving. A cheap char/4 token estimate (no tokenizer dependency, provider-
agnostic) picks one of three modes:

    FULL_CONTEXT  — a single doc that fits comfortably → one comprehension call over the whole text.
    SECTIONED     — too big for one call but tractable → map-reduce comprehension over sections.
    RETRIEVAL     — a corpus far larger than context → RAG retrieves spans to build the blueprint.

``context_token_budget`` is the model's usable context (from config); swapping in a long-context
model just raises the threshold without any code change.
"""

from __future__ import annotations

from enum import Enum


class SourceMode(str, Enum):
    FULL_CONTEXT = "full_context"
    SECTIONED = "sectioned"
    RETRIEVAL = "retrieval"


def estimate_tokens(text: str) -> int:
    """Rough, provider-agnostic token estimate. ~4 chars/token is good enough for routing."""
    return len(text) // 4


def route(*, total_chars: int, n_docs: int, context_token_budget: int) -> SourceMode:
    """Choose a comprehension strategy from corpus size.

    Thresholds leave headroom for the prompt + structured output: a single doc goes FULL_CONTEXT only
    if it uses under ~60% of the budget; a handful of comprehension passes (under ~4x budget) is still
    SECTIONED; anything larger falls back to RETRIEVAL.
    """
    est_tokens = max(0, total_chars) // 4
    if n_docs <= 1 and est_tokens < int(context_token_budget * 0.6):
        return SourceMode.FULL_CONTEXT
    if est_tokens < context_token_budget * 4:
        return SourceMode.SECTIONED
    return SourceMode.RETRIEVAL
