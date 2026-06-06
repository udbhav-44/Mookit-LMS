"""UK.4 (part 1) — fake RAG retrieve().

Backed by an in-memory chunked sample document. Returns spans with stable locators so Dev B's quiz
pipeline can attach citations and tests can assert citation→source round-trips.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.contracts.types import RequestContext


class RetrievedSpan(BaseModel):
    span_id: str
    text: str
    locator: dict  # e.g. {"doc_id": ..., "page": 2, "char_start": 100, "char_end": 240}


# A seeded "document": each chunk is a (span_id, text, locator) triple.
_SAMPLE_CHUNKS: list[RetrievedSpan] = [
    RetrievedSpan(
        span_id="s1",
        text=(
            "Photosynthesis is the process by which green plants convert light energy into "
            "chemical energy stored in glucose. It occurs in the chloroplasts."
        ),
        locator={"doc_id": "sample", "page": 1, "char_start": 0, "char_end": 150},
    ),
    RetrievedSpan(
        span_id="s2",
        text=(
            "The light-dependent reactions take place in the thylakoid membranes and produce "
            "ATP and NADPH, releasing oxygen as a by-product of splitting water."
        ),
        locator={"doc_id": "sample", "page": 1, "char_start": 151, "char_end": 320},
    ),
    RetrievedSpan(
        span_id="s3",
        text=(
            "The Calvin cycle (light-independent reactions) occurs in the stroma and fixes carbon "
            "dioxide into glucose using the ATP and NADPH from the light reactions."
        ),
        locator={"doc_id": "sample", "page": 2, "char_start": 0, "char_end": 170},
    ),
    RetrievedSpan(
        span_id="s4",
        text=(
            "Chlorophyll a is the primary pigment that absorbs mostly blue and red light, "
            "reflecting green light, which gives plants their color."
        ),
        locator={"doc_id": "sample", "page": 2, "char_start": 171, "char_end": 320},
    ),
]


async def retrieve(
    ctx: RequestContext,
    doc_artifact_id: str,
    query: str,
    k: int = 4,
) -> list[RetrievedSpan]:
    """Naive lexical-overlap retrieval over the seeded corpus.

    Returns up to ``k`` spans ranked by query-term overlap; falls back to corpus order so callers
    always get evidence for the seeded doc. An unknown doc yields an empty list (no hallucinated span).
    """
    if doc_artifact_id in {"", "missing", "unknown"}:
        return []
    if not query:
        return _SAMPLE_CHUNKS[:k]
    q_terms = {t.lower() for t in query.split()}
    scored = sorted(
        _SAMPLE_CHUNKS,
        key=lambda c: len(q_terms & {w.lower().strip(".,()") for w in c.text.split()}),
        reverse=True,
    )
    return scored[:k]


def sample_corpus() -> list[RetrievedSpan]:
    return list(_SAMPLE_CHUNKS)
