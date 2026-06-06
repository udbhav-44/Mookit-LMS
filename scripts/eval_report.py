"""Generate eval-report metrics from the offline pipeline + eval harness.

Run from the repo root: ``python scripts/eval_report.py``. Uses the deterministic test fakes so the
numbers are reproducible without an OpenAI key. The eval *library* lives in ``app/evals``; this is just
the runner that wires the fakes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contracts import Artifact, RequestContext  # noqa: E402

from app.core.orchestrator import Orchestrator  # noqa: E402
from app.core.reference_resolver import ReferenceResolver  # noqa: E402
from app.evals.hallucination import measure_grounding  # noqa: E402
from app.evals.injection_redteam import DEFAULT_CASES, run_redteam  # noqa: E402
from app.evals.quiz_quality import score_quiz  # noqa: E402
from app.gen.provenance import stamp  # noqa: E402
from app.gen.quiz.params import QuizParams  # noqa: E402
from app.gen.quiz.pipeline import QuizPipeline  # noqa: E402
from app.tools.announcement import SendAnnouncementTool  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402
from tests.core.scripted_llm import ScriptedLLM, tool_round  # noqa: E402
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient  # noqa: E402
from tests.fakes.fake_rag import retrieve, sample_corpus  # noqa: E402
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore  # noqa: E402
from tests.gen.fake_generator import fake_generator  # noqa: E402


async def _main() -> dict:
    ctx = RequestContext(
        instance_id="hello.iitk.ac.in",
        course_id="coursetest",
        user_id=1,
        session_id="eval",
        permissions=ALL_PERMISSIONS,
    )

    reg = InMemoryArtifactRegistry()
    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator)
    mix = {"mcq_single": 1, "mcq_multi": 1, "true_false": 1, "fib": 1, "descriptive": 1}
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Photosynthesis", params=QuizParams(count=5, type_mix=mix)
    )
    questions = draft.payload["questions"]
    doc_text = "\n".join(s.text for s in sample_corpus())

    quality = await score_quiz(questions=questions, doc_text=doc_text)
    grounding = measure_grounding(questions, [s.text for s in sample_corpus()])

    mookit = FakeMooKitClient()
    seed = Artifact(
        id="",
        type="announcement_draft",
        title="x",
        status="draft",
        payload={"title": "x", "description": "y", "type": "urgent", "notify_mail": True, "audience_intent": "all"},
        provenance=stamp(ai_generated=True, edited_by_human=False, source_ids=[]),
    )
    did = await reg.add(ctx, seed)
    rt_registry = ToolRegistry()
    rt_registry.register(SendAnnouncementTool(reg))
    llm = ScriptedLLM(
        [
            tool_round(name="send_announcement", call_id="c", arguments={"draft_id": did}, response_id="r1")
            for _ in DEFAULT_CASES
        ]
    )
    orch = Orchestrator(
        llm=llm,
        registry=rt_registry,
        sessions=InMemorySessionStore(),
        artifacts=reg,
        resolver=ReferenceResolver(reg),
        mookit=mookit,
    )
    redteam = await run_redteam(orch, ctx, DEFAULT_CASES, write_probe=lambda: len(mookit.write_calls))

    return {
        "quiz_quality": {"scores": quality.scores, "overall": quality.overall, "flagged": quality.flagged_count},
        "grounding": {
            "total": grounding.total,
            "ungrounded": grounding.ungrounded,
            "unfaithful_citations": grounding.unfaithful_citations,
            "ungrounded_rate": grounding.ungrounded_rate,
            "faithful": grounding.faithful,
        },
        "injection_redteam": {
            "cases": redteam.total,
            "unconfirmed_actions": redteam.unconfirmed_actions,
            "pending_confirmations": redteam.pending_confirmations,
            "passed": redteam.passed,
        },
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(_main()), indent=2))
