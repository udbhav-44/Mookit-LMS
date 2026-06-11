"""Phase 3 — independent LLM solve-critique (flag mapping + pipeline integration)."""

from collections.abc import AsyncIterator

from app.contracts.llm import LLMEvent, LLMProvider
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import Citation, MCQSingle, Option
from app.gen.quiz.solve_verify import LLMSolveCritique, SolveVerdict
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


class _FakeProvider(LLMProvider):
    """Returns a preset SolveVerdict from respond_structured; respond is unused here."""

    def __init__(self, verdict: SolveVerdict) -> None:
        self._verdict = verdict

    def respond(self, **kwargs) -> AsyncIterator[LLMEvent]:  # pragma: no cover - unused
        async def _empty() -> AsyncIterator[LLMEvent]:
            if False:  # pragma: no cover — makes this a (never-yielding) async generator
                yield LLMEvent(event_type="", data=None)

        return _empty()

    async def respond_structured(self, **kwargs) -> SolveVerdict:
        return self._verdict


def _question() -> MCQSingle:
    return MCQSingle(
        questionText="Where does the Calvin cycle occur?",
        citation=Citation(source_id="doc-1", locator={}, quote="the stroma"),
        options=[
            Option(optionText="Stroma", isCorrect=True),
            Option(optionText="Thylakoid", isCorrect=False),
        ],
    )


_EVID = [Evidence(span_id="s", text="The Calvin cycle occurs in the stroma.", locator={})]


async def test_agreement_yields_no_flags() -> None:
    v = SolveVerdict(answerable_from_evidence=True, derived_answer="stroma", agrees_with_key=True,
                     ambiguity="none", confidence=0.9, reason="ok")
    flags = await LLMSolveCritique(_FakeProvider(v))(_question(), _EVID)
    assert flags == []


async def test_disagreement_flagged() -> None:
    v = SolveVerdict(answerable_from_evidence=True, derived_answer="thylakoid", agrees_with_key=False,
                     ambiguity="none", confidence=0.8, reason="key looks wrong")
    flags = await LLMSolveCritique(_FakeProvider(v))(_question(), _EVID)
    assert "solve_disagreement" in flags


async def test_unsolvable_flagged() -> None:
    v = SolveVerdict(answerable_from_evidence=False, derived_answer="", agrees_with_key=False,
                     ambiguity="underspecified", confidence=0.3, reason="evidence insufficient")
    flags = await LLMSolveCritique(_FakeProvider(v))(_question(), _EVID)
    assert "unsolvable_from_evidence" in flags and "ambiguous" in flags


async def test_no_evidence_skips_call() -> None:
    # With no evidence there is nothing to solve against → no flags, no provider call.
    v = SolveVerdict(answerable_from_evidence=False, derived_answer="", agrees_with_key=False,
                     ambiguity="none", confidence=0.0, reason="")
    flags = await LLMSolveCritique(_FakeProvider(v))(_question(), [])
    assert flags == []


async def test_critique_flags_flow_through_pipeline(ctx) -> None:
    async def always_disagree(question, evidence) -> list[str]:
        return ["solve_disagreement"]

    reg = InMemoryArtifactRegistry()
    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator, critique=always_disagree)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=2, type_mix={"mcq_single": 2}),
    )
    for q in draft.payload["questions"]:
        assert "solve_disagreement" in q["flags"]
    assert any("verification flag" in w for w in draft.payload["warnings"])
