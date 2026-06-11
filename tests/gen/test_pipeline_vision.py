"""Phase 2 — vision comprehension path (render PDF pages → multimodal comprehend → ground/flag).

Uses the real pypdfium2 renderer on an in-process blank PDF and a fake vision comprehender, so the
whole path runs offline without an LLM. A separate test asserts the vision content blocks include one
image per page.
"""

import io

import pytest

from app.contracts import RequestContext
from app.files.render import render_pdf_to_images
from app.gen.quiz.blueprint import (
    Blueprint,
    ConceptNode,
    LearningObjective,
    build_vision_content,
)
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator

_FORMULA_TEXT = "The governing relation is F = m a, derived in lecture."


def _blank_pdf(n_pages: int = 2) -> bytes:
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        pdf.new_page(200, 200)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


async def _fetch_all(ctx: RequestContext, doc_id: str) -> list[dict]:
    # Extracted text used for grounding (deliberately missing the verbatim formula).
    return [{"chunk_index": 0, "text": _FORMULA_TEXT}]


async def _fetch_source(ctx: RequestContext, doc_id: str) -> bytes:
    return _blank_pdf()


async def _vision_comprehender(*, images: list[bytes], params) -> Blueprint:
    # A vision model "reads" a formula off the page image; its quote IS present in the extracted text.
    return Blueprint(
        objectives=[LearningObjective(id="o1", statement="Apply F=ma", bloom="apply", concept_ids=["c1"])],
        concepts=[
            ConceptNode(
                id="c1", name="Newton's second law", summary="F=ma", kind="quantitative",
                representative_quote="The governing relation is F = m a, derived in lecture.",
                suggested_bloom=["apply"], formulas=["F = m a"], units=["N"],
            )
        ],
        quantitative_ratio=1.0,
    )


def _vision_pipeline() -> QuizPipeline:
    return QuizPipeline(
        retrieve=retrieve,
        generator=fake_generator,
        fetch_all=_fetch_all,
        vision_comprehender=_vision_comprehender,
        fetch_source=_fetch_source,
        render_pages=render_pdf_to_images,
    )


def test_build_vision_content_has_one_image_block_per_page() -> None:
    images = [b"png1", b"png2", b"png3"]
    content = build_vision_content(images, QuizParams())
    image_blocks = [c for c in content if c["type"] == "input_image"]
    assert len(image_blocks) == 3
    assert all(c["image_url"].startswith("data:image/png;base64,") for c in image_blocks)
    assert any(c["type"] == "input_text" for c in content)  # instruction precedes the images


async def test_vision_path_produces_questions(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _vision_pipeline()
    assert pipe._vision_enabled
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Mechanics",
        params=QuizParams(count=2, bloom_level="apply", type_mix={"mcq_single": 2}),
    )
    qs = draft.payload["questions"]
    assert qs
    # Quantitative concept → numeric fib items, grounded and citing the source.
    assert all(q["questionType"] == "fib" for q in qs)
    assert all(q["citation"]["quote"].strip() for q in qs)


async def test_vision_unmatched_formula_is_flagged_not_dropped(ctx: RequestContext) -> None:
    """A vision-read quote absent from extracted text is kept-but-flagged for review."""
    reg = InMemoryArtifactRegistry()

    async def fetch_all_no_formula(c: RequestContext, doc_id: str) -> list[dict]:
        return [{"chunk_index": 0, "text": "Unrelated extracted text with no formula."}]

    pipe = QuizPipeline(
        retrieve=retrieve, generator=fake_generator, fetch_all=fetch_all_no_formula,
        vision_comprehender=_vision_comprehender, fetch_source=_fetch_source,
        render_pages=render_pdf_to_images,
    )
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="M",
        params=QuizParams(count=1, bloom_level="apply", type_mix={"mcq_single": 1}),
    )
    # The concept survived (not dropped) and the draft carries an "unverified" review warning.
    assert draft.payload["questions"]
    assert any("unverified" in w for w in draft.payload["warnings"])
