"""Verbatim question-paper replication.

When an instructor uploads an existing exam / question paper and asks to "replicate" it, we do
NOT generate fresh questions — we reproduce the questions and options exactly as written. This
module:

  * defines the seam (``Replicator``) that turns rendered page images into structured verbatim
    questions, plus an OpenAI vision implementation;
  * maps those verbatim records onto the per-type quiz schemas (``MCQSingle`` etc.), preserving
    the original wording and grounding each question's citation in the source page.

Answer keys: many question papers don't print the correct answer. When the key for a question
can't be detected we keep the question, mark the first option correct as a placeholder, and add
an ``answer_key_unverified`` flag so the instructor sets it before publishing.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.diagrams.models import DiagramInfo
from app.gen.quiz.schemas import (
    Citation,
    Descriptive,
    MCQMulti,
    MCQSingle,
    Option,
    TrueFalse,
    _QuestionBase,
)

logger = logging.getLogger(__name__)

VerbatimType = Literal["mcq_single", "mcq_multi", "true_false", "descriptive"]


class VerbatimOption(BaseModel):
    text: str
    is_correct: bool = False


class VerbatimQuestion(BaseModel):
    question_type: VerbatimType = "mcq_single"
    question_text: str
    options: list[VerbatimOption] = Field(default_factory=list)
    # 0/1 for true_false when the paper states the answer; None when unknown.
    true_false_answer: int | None = None
    # True only when the paper itself indicates the correct answer(s).
    answer_key_detected: bool = False
    source_quote: str = ""
    page_number: int | None = None
    # The printed question number/label (e.g. "Q3", "12a") when present — used to align
    # the transcribed question with the separately-extracted diagram for the same item.
    question_number: str | None = None
    # True when the question references a figure/diagram printed on the page that the
    # student needs in order to answer it.
    has_diagram: bool = False


class ReplicateResult(BaseModel):
    questions: list[VerbatimQuestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Replicator(Protocol):
    async def __call__(
        self, *, images: list[bytes], page_texts: list[str]
    ) -> ReplicateResult: ...


# ---------------------------------------------------------------------------
# Mapping verbatim records → validated quiz-schema questions
# ---------------------------------------------------------------------------

def verbatim_to_questions(
    result: ReplicateResult,
    source_id: str,
    diagrams: list[DiagramInfo] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Map verbatim records onto the per-type schemas. Returns (question_dicts, warnings).

    Each record is reproduced as written. Records that can't form a valid typed question
    (e.g. an MCQ with <2 options) fall back to a descriptive item so nothing is silently lost.

    When ``diagrams`` (cropped figures already extracted from the same source PDF) are supplied,
    each question is matched to the diagram printed alongside it on the same page and the
    reference is attached as a ``diagram`` field on the question dict, so the UI can preview the
    figure with its question. Matching is deterministic (same page + question-number/text
    overlap) and never double-assigns a diagram.
    """
    questions: list[tuple[_QuestionBase, VerbatimQuestion]] = []
    unverified = 0
    for v in result.questions:
        try:
            q, key_missing = _to_question(v, source_id)
        except Exception as exc:  # noqa: BLE001 — one malformed record must not abort the paper
            logger.warning("Skipping unmappable verbatim question: %s", exc)
            continue
        if key_missing:
            unverified += 1
        questions.append((q, v))

    dicts: list[dict[str, Any]] = [q.model_dump() for q, _ in questions]
    attached = _attach_diagrams(dicts, [v for _, v in questions], diagrams or [], source_id)

    warnings = list(result.warnings)
    if not dicts:
        warnings.append("no_questions_extracted")
    if unverified:
        warnings.append(
            f"{unverified} question(s) had no detectable answer key — set the correct answer before publishing"
        )
    higher = sum(1 for q, _ in questions if q.is_higher_order)
    if higher:
        warnings.append(f"{higher} higher-order Bloom question(s) — review carefully")
    if attached:
        warnings.append(f"{attached} question(s) have an attached diagram preview")
    return dicts, warnings


def _norm_words(text: str) -> set[str]:
    return {w for w in (text or "").lower().split() if w}


def _qnum_norm(label: str | None) -> str:
    """Normalise a question label (``"Q.3"`` / ``"3)"`` / ``"3a"``) to a comparable token."""
    if not label:
        return ""
    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def _attach_diagrams(
    dicts: list[dict[str, Any]],
    sources: list[VerbatimQuestion],
    diagrams: list[DiagramInfo],
    source_id: str,
) -> int:
    """Attach the best-matching diagram to each question dict in place. Returns the count attached.

    A diagram is only ever attached to one question. Within a page we prefer an exact
    question-number match, then fall back to word-overlap (Jaccard) of the question text,
    requiring at least 30% overlap to avoid false positives — the same threshold the publish
    executor uses when wiring diagram fileIds, so preview and publish stay consistent.
    """
    if not diagrams:
        return 0

    by_page: dict[int | None, list[DiagramInfo]] = {}
    for info in diagrams:
        by_page.setdefault(info.page_number, []).append(info)

    used: set[str] = set()
    attached = 0
    for qdict, vq in zip(dicts, sources):
        candidates = [d for d in by_page.get(vq.page_number, []) if d.diagram_file not in used]
        if not candidates:
            continue
        best = _best_diagram(vq, candidates)
        if best is None:
            continue
        used.add(best.diagram_file)
        qdict["diagram"] = {
            "file_id": source_id,
            "diagram_file": best.diagram_file,
            "description": best.diagram_description or "",
            "page": best.page_number,
            "question_number": best.question_number or vq.question_number or "",
        }
        attached += 1
    return attached


def _best_diagram(
    vq: VerbatimQuestion, candidates: list[DiagramInfo]
) -> DiagramInfo | None:
    # 1) Exact question-number match is the strongest signal.
    vq_num = _qnum_norm(vq.question_number)
    if vq_num:
        for d in candidates:
            if _qnum_norm(d.question_number) == vq_num:
                return d

    # 2) Otherwise, word-overlap of the question text on the same page.
    q_words = _norm_words(vq.question_text)
    best: DiagramInfo | None = None
    best_score = 0.0
    for d in candidates:
        union = q_words | _norm_words(d.question_text)
        if not union:
            continue
        score = len(q_words & _norm_words(d.question_text)) / len(union)
        if score > best_score:
            best_score, best = score, d
    if best is not None and best_score >= 0.30:
        return best

    # 3) Fallback: the replicator flagged a diagram and exactly one diagram sits on this
    #    page, so the association is unambiguous.
    if vq.has_diagram and len(candidates) == 1:
        return candidates[0]
    return None


def _citation(v: VerbatimQuestion, source_id: str) -> Citation:
    quote = (v.source_quote or v.question_text or "").strip() or "(verbatim question)"
    locator: dict[str, Any] = {"verbatim": True}
    if v.page_number is not None:
        locator["page"] = v.page_number
    return Citation(source_id=source_id, locator=locator, quote=quote)


def _to_question(v: VerbatimQuestion, source_id: str) -> tuple[_QuestionBase, bool]:
    """Return (question, answer_key_missing). Falls back to Descriptive when structure is unusable."""
    citation = _citation(v, source_id)
    base = {
        "questionText": v.question_text.strip(),
        "citation": citation,
        "flags": ["verbatim"],
    }

    if v.question_type == "true_false":
        if v.true_false_answer in (0, 1):
            return TrueFalse(trueFalseAnswer=v.true_false_answer, **base), False
        return (
            TrueFalse(trueFalseAnswer=1, **{**base, "flags": ["verbatim", "answer_key_unverified"]}),
            True,
        )

    if v.question_type in ("mcq_single", "mcq_multi") and len(v.options) >= 2:
        return _to_mcq(v, base)

    # descriptive, or an MCQ we couldn't reconstruct → keep the prompt verbatim as descriptive.
    return Descriptive(**base), False


def _to_mcq(v: VerbatimQuestion, base: dict[str, Any]) -> tuple[_QuestionBase, bool]:
    correct_idx = [i for i, o in enumerate(v.options) if o.is_correct]
    key_missing = not (v.answer_key_detected and correct_idx)

    if v.question_type == "mcq_multi":
        marks = correct_idx if (v.answer_key_detected and correct_idx) else [0]
        options = [
            Option(optionText=o.text.strip(), isCorrect=(i in marks))
            for i, o in enumerate(v.options)
        ]
        flags = ["verbatim"] + (["answer_key_unverified"] if key_missing else [])
        return MCQMulti(options=options, **{**base, "flags": flags}), key_missing

    # mcq_single — exactly one correct.
    chosen = correct_idx[0] if (v.answer_key_detected and correct_idx) else 0
    options = [
        Option(optionText=o.text.strip(), isCorrect=(i == chosen))
        for i, o in enumerate(v.options)
    ]
    flags = ["verbatim"] + (["answer_key_unverified"] if key_missing else [])
    return MCQSingle(options=options, **{**base, "flags": flags}), key_missing


# ---------------------------------------------------------------------------
# OpenAI vision implementation of the Replicator seam
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """
You are a precise exam-transcription assistant. The image is one page of an existing question
paper. Transcribe EVERY question on the page VERBATIM — do not invent, rephrase, summarize, or
add questions. Preserve the original wording of stems and answer choices exactly.

For each question return a JSON object with:
  - question_type: one of "mcq_single" (one correct choice), "mcq_multi" (multiple correct),
    "true_false", or "descriptive" (open-ended / no choices). Infer from the layout.
  - question_text: the full question stem exactly as written (exclude the answer choices).
  - options: list of {"text": "...", "is_correct": bool} for choices in reading order
    (empty list for true_false / descriptive). Mark is_correct TRUE only if the paper itself
    indicates the answer (key, highlight, checkmark, "Ans:"); otherwise set every is_correct false.
  - true_false_answer: 1 for true, 0 for false, only if the paper states it; else null.
  - answer_key_detected: true ONLY if the correct answer is indicated on the page.
  - source_quote: a short exact snippet of the question as it appears (for grounding).
  - question_number: the printed question label exactly as shown (e.g. "Q3", "12", "5a"),
    or null if the question is unnumbered.
  - has_diagram: true ONLY if the question depends on a figure, diagram, circuit, graph,
    chart, or image printed on the page that a student needs in order to answer it; else false.

Return a JSON object: {"questions": [...]} in the order they appear. If the page has no
questions, return {"questions": []}.
""".strip()


class OpenAIQuestionPaperReplicator:
    """Transcribes verbatim questions from rendered page images using an OpenAI vision model."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def __call__(self, *, images: list[bytes], page_texts: list[str]) -> ReplicateResult:
        questions: list[VerbatimQuestion] = []
        warnings: list[str] = []
        if not images:
            return ReplicateResult(questions=[], warnings=["no_renderable_pages"])
        for idx, img in enumerate(images):
            page_no = idx + 1
            text = page_texts[idx] if idx < len(page_texts) else ""
            try:
                page_qs = await self._extract_page(img, page_no, text)
            except Exception as exc:  # noqa: BLE001 — keep the pages we can transcribe
                logger.error("Replicator failed on page %d: %s", page_no, exc)
                warnings.append(f"page_{page_no}_extraction_failed")
                continue
            questions.extend(page_qs)
        return ReplicateResult(questions=questions, warnings=warnings)

    async def _extract_page(
        self, image: bytes, page_no: int, text: str
    ) -> list[VerbatimQuestion]:
        b64 = base64.b64encode(image).decode("utf-8")
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            },
            {
                "type": "text",
                "text": (
                    f"Page {page_no}. Transcribe all questions verbatim.\n"
                    f"Extracted text (reference only — the image is authoritative):\n"
                    f"{text if text else '[no extractable text]'}"
                ),
            },
        ]
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
        )
        raw = resp.choices[0].message.content or "{}"
        payload = json.loads(raw)
        out: list[VerbatimQuestion] = []
        for q in payload.get("questions", []):
            try:
                vq = VerbatimQuestion.model_validate(q)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Malformed verbatim question on page %d: %s", page_no, exc)
                continue
            vq.page_number = page_no
            out.append(vq)
        return out
