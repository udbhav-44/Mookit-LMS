"""Verbatim question-paper replication: mapping + pipeline.build_replica."""

from app.diagrams.models import DiagramExtractionResult, DiagramInfo
from app.gen.quiz.pipeline import QuizPipeline
from app.gen.quiz.replicate import (
    ReplicateResult,
    VerbatimOption,
    VerbatimQuestion,
    verbatim_to_questions,
)
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


def _diagram(page: int, qtext: str, file: str, qnum: str | None = None) -> DiagramInfo:
    return DiagramInfo(
        page_number=page,
        question_index=0,
        question_number=qnum,
        question_text=qtext,
        diagram_description="circuit diagram",
        diagram_file=file,
        diagram_path=f"/tmp/{file}",
    )


def test_mcq_single_with_detected_key_is_verbatim() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="mcq_single",
                question_text="What is 2+2?",
                options=[
                    VerbatimOption(text="3", is_correct=False),
                    VerbatimOption(text="4", is_correct=True),
                ],
                answer_key_detected=True,
                page_number=1,
            )
        ]
    )
    qs, warnings = verbatim_to_questions(result, "doc-1")
    assert len(qs) == 1
    q = qs[0]
    assert q["questionType"] == "mcq_single"
    assert q["questionText"] == "What is 2+2?"
    assert [o["isCorrect"] for o in q["options"]] == [False, True]
    assert "verbatim" in q["flags"]
    assert not any("answer key" in w for w in warnings)


def test_missing_answer_key_flags_and_warns() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="mcq_single",
                question_text="Capital of France?",
                options=[VerbatimOption(text="Paris"), VerbatimOption(text="Rome")],
                answer_key_detected=False,
            )
        ]
    )
    qs, warnings = verbatim_to_questions(result, "doc-1")
    assert "answer_key_unverified" in qs[0]["flags"]
    assert any("answer key" in w for w in warnings)


def test_mcq_with_too_few_options_falls_back_to_descriptive() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="mcq_single",
                question_text="Explain entropy.",
                options=[VerbatimOption(text="only one")],
            )
        ]
    )
    qs, _ = verbatim_to_questions(result, "doc-1")
    assert qs[0]["questionType"] == "descriptive"


def test_diagram_attached_by_question_number() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="descriptive",
                question_text="Find the current through R2 in the circuit shown.",
                page_number=2,
                question_number="Q5",
                has_diagram=True,
            ),
        ]
    )
    diagrams = [_diagram(2, "totally different wording", "p2_q5.png", qnum="Q5")]
    qs, warnings = verbatim_to_questions(result, "doc-1", diagrams)
    assert qs[0]["diagram"]["file_id"] == "doc-1"
    assert qs[0]["diagram"]["diagram_file"] == "p2_q5.png"
    assert any("attached diagram" in w for w in warnings)


def test_diagram_attached_by_text_overlap_same_page() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="descriptive",
                question_text="Calculate the area of the shaded triangle below.",
                page_number=1,
            ),
        ]
    )
    diagrams = [_diagram(1, "area of the shaded triangle", "p1.png")]
    qs, _ = verbatim_to_questions(result, "doc-1", diagrams)
    assert qs[0].get("diagram", {}).get("diagram_file") == "p1.png"


def test_diagram_not_attached_across_pages() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="descriptive",
                question_text="Describe the diagram.",
                page_number=1,
                has_diagram=True,
            ),
        ]
    )
    # Diagram lives on a different page → no match (page numbers must align).
    diagrams = [_diagram(3, "Describe the diagram.", "p3.png")]
    qs, _ = verbatim_to_questions(result, "doc-1", diagrams)
    assert "diagram" not in qs[0]


def test_one_diagram_never_assigned_twice() -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(question_type="descriptive", question_text="Use figure A.", page_number=1, has_diagram=True),
            VerbatimQuestion(question_type="descriptive", question_text="Use figure A again.", page_number=1, has_diagram=True),
        ]
    )
    diagrams = [_diagram(1, "Use figure A.", "only.png")]
    qs, _ = verbatim_to_questions(result, "doc-1", diagrams)
    attached = [q for q in qs if "diagram" in q]
    assert len(attached) == 1


class _FakeReplicator:
    def __init__(self, result: ReplicateResult) -> None:
        self._result = result

    async def __call__(self, *, images, page_texts) -> ReplicateResult:  # noqa: ANN001
        return self._result


def _replicate_pipeline(
    result: ReplicateResult, diagrams: list[DiagramInfo] | None = None
) -> QuizPipeline:
    async def fetch_source(ctx, doc_id):  # noqa: ANN001
        return b"%PDF-fake"

    fetch_diagrams = None
    if diagrams is not None:
        async def fetch_diagrams(ctx, doc_id):  # noqa: ANN001
            return DiagramExtractionResult(
                file_id=doc_id, diagrams=diagrams, total_pages=1, total_diagrams=len(diagrams)
            )

    return QuizPipeline(
        retrieve=retrieve,
        generator=fake_generator,
        fetch_source=fetch_source,
        render_pages=lambda data: [b"page-image"],
        replicator=_FakeReplicator(result),
        fetch_diagrams=fetch_diagrams,
    )


async def test_build_replica_links_diagrams(ctx) -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="descriptive",
                question_text="Identify the labelled parts of the cell.",
                page_number=1,
                question_number="1",
                has_diagram=True,
            ),
        ]
    )
    diagrams = [_diagram(1, "Identify the labelled parts of the cell.", "cell.png", qnum="1")]
    reg = InMemoryArtifactRegistry()
    pipeline = _replicate_pipeline(result, diagrams)
    art = await pipeline.build_replica(ctx, reg, doc_artifact_id="doc-1", title="Bio Exam")
    q = art.payload["questions"][0]
    assert q["diagram"]["diagram_file"] == "cell.png"
    assert q["diagram"]["file_id"] == "doc-1"


async def test_build_replica_persists_verbatim_draft(ctx) -> None:
    result = ReplicateResult(
        questions=[
            VerbatimQuestion(
                question_type="true_false",
                question_text="The sky is blue.",
                true_false_answer=1,
                answer_key_detected=True,
            ),
            VerbatimQuestion(
                question_type="mcq_single",
                question_text="Pick one.",
                options=[VerbatimOption(text="a", is_correct=True), VerbatimOption(text="b")],
                answer_key_detected=True,
            ),
        ]
    )
    reg = InMemoryArtifactRegistry()
    pipeline = _replicate_pipeline(result)
    assert pipeline.replicate_enabled
    art = await pipeline.build_replica(ctx, reg, doc_artifact_id="doc-1", title="Reproduced Exam")
    assert art.type == "assessment_draft"
    assert art.payload["mode"] == "replicate"
    assert len(art.payload["questions"]) == 2
    assert art.provenance["ai_generated"] is False
