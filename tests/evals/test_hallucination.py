"""B4.4 acceptance — ungrounded detected; faithful draft clean."""

from app.evals.hallucination import measure_grounding

EVID = [
    "Photosynthesis occurs in the chloroplast.",
    "The Calvin cycle occurs in the stroma.",
]


def test_faithful_draft_clean() -> None:
    questions = [
        {"citation": {"quote": "Photosynthesis occurs in the chloroplast."}},
        {"citation": {"quote": "The Calvin cycle occurs in the stroma."}},
    ]
    report = measure_grounding(questions, EVID)
    assert report.ungrounded == 0
    assert report.unfaithful_citations == 0
    assert report.faithful is True
    assert report.ungrounded_rate == 0.0


def test_ungrounded_detected() -> None:
    questions = [{"citation": {"quote": ""}}]
    report = measure_grounding(questions, EVID)
    assert report.ungrounded == 1
    assert report.faithful is False


def test_unfaithful_citation_detected() -> None:
    questions = [{"citation": {"quote": "Mitochondria are the powerhouse and unrelated to this text"}}]
    report = measure_grounding(questions, EVID)
    assert report.unfaithful_citations == 1
