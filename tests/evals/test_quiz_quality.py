"""B4.3 acceptance — report shape + regression detection on a degraded draft."""

from app.evals.quiz_quality import baseline_compare, score_quiz
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve, sample_corpus
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


async def _draft_questions(ctx) -> list[dict]:
    reg = InMemoryArtifactRegistry()
    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator)
    mix = {"mcq_single": 1, "mcq_multi": 1, "true_false": 1, "fib": 1, "descriptive": 1}
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=QuizParams(count=5, type_mix=mix)
    )
    return draft.payload["questions"]


def _doc_text() -> str:
    return "\n".join(s.text for s in sample_corpus())


async def test_report_shape(ctx) -> None:
    report = await score_quiz(questions=await _draft_questions(ctx), doc_text=_doc_text())
    assert set(report.scores.keys()) == {
        "understandability",
        "relevance",
        "grammar",
        "clarity",
        "answerability",
        "bloom_alignment",
    }
    assert 0.0 <= report.overall <= 1.0


async def test_regression_detected_on_degraded(ctx) -> None:
    report = await score_quiz(questions=await _draft_questions(ctx), doc_text=_doc_text())
    # A baseline with very high answerability; degrade by comparing a draft with a broken question.
    baseline = dict.fromkeys(report.scores.keys(), 1.0)
    reg = baseline_compare(report, baseline, tol=0.01)
    # The fake draft includes a higher? no — all understand-level; answerability should be high.
    # Construct an explicit degraded comparison to prove the detector fires.
    degraded = await score_quiz(
        questions=[{"questionType": "mcq_single", "questionText": "q", "options": [], "citation": {}}],
        doc_text=_doc_text(),
    )
    reg2 = baseline_compare(degraded, baseline, tol=0.05)
    assert reg2.has_regression
    assert "answerability" in reg2.regressed
    _ = reg
