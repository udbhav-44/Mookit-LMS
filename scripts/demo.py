"""Human-readable end-to-end demo of the three flows + the security gate.

Run from the repo root:
    python scripts/demo.py            # deterministic fakes (no OpenAI key needed)
    python scripts/demo.py --live     # use the real OpenAI generator (needs OPENAI_API_KEY)

It prints, step by step, what the assistant produces: a grounded quiz draft (with per-question source
citations + verification flags), the publish *preview*, the confirm → live write, an announcement flow
(audience chip + channel), a lecture flow (diff), and the injection red-team result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contracts import Artifact, RequestContext  # noqa: E402
from app.core.orchestrator import Orchestrator  # noqa: E402
from app.core.reference_resolver import ReferenceResolver  # noqa: E402
from app.evals.injection_redteam import DEFAULT_CASES, run_redteam  # noqa: E402
from app.gen.provenance import stamp  # noqa: E402
from app.gen.quiz.params import QuizParams  # noqa: E402
from app.gen.quiz.pipeline import QuizPipeline  # noqa: E402
from app.tools.announcement import DraftAnnouncementTool, SendAnnouncementTool  # noqa: E402
from app.tools.assessment import EditQuizTool, PublishAssessmentTool  # noqa: E402
from app.tools.lecture import DraftLectureTool, PublishLectureTool  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402
from tests.core.scripted_llm import ScriptedLLM, tool_round  # noqa: E402
from tests.fakes.confirm_harness import ConfirmHarness  # noqa: E402
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient  # noqa: E402
from tests.fakes.fake_rag import retrieve  # noqa: E402
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore  # noqa: E402
from tests.gen.fake_generator import fake_generator  # noqa: E402

C_HEAD = "\033[1;36m"
C_OK = "\033[1;32m"
C_WARN = "\033[1;33m"
C_DIM = "\033[2m"
C_END = "\033[0m"


def h(title: str) -> None:
    print(f"\n{C_HEAD}{'=' * 70}\n{title}\n{'=' * 70}{C_END}")


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in",
        course_id="coursetest",
        user_id=1,
        session_id="demo",
        permissions=ALL_PERMISSIONS,
    )


def _generator(live: bool):
    if not live:
        return fake_generator
    from openai import AsyncOpenAI

    from app.config import get_settings
    from app.gen.quiz.generator import OpenAIQuestionGenerator
    from app.llm.openai import OpenAIProvider

    s = get_settings()
    client = AsyncOpenAI(api_key=s.openai.api_key.get_secret_value())
    provider = OpenAIProvider(client, default_model=s.openai.model)
    return OpenAIQuestionGenerator(provider, temperature=s.openai.quiz_temperature)


async def demo_quiz(ctx, reg, mookit, harness, live: bool) -> None:
    h("FLOW 1 — Quiz from a document  (\"Create a quiz from this PDF\")")
    pipe = QuizPipeline(retrieve=retrieve, generator=_generator(live))
    mix = {"mcq_single": 1, "mcq_multi": 1, "true_false": 1, "fib": 1, "descriptive": 1}

    # CreateQuizTool wraps this for the agent; for a varied demo we call the pipeline directly.
    try:
        draft = await pipe.build_draft(
            ctx, reg, doc_artifact_id="doc-1", title="Photosynthesis Quiz", params=QuizParams(count=5, type_mix=mix)
        )
    except Exception as exc:  # noqa: BLE001 — surface API/network errors as a friendly message
        if live:
            print(f"{C_WARN}Live generation failed: {type(exc).__name__}: {exc}{C_END}")
            print(f"{C_DIM}(Falling back to the deterministic fake generator for the rest of the demo.){C_END}")
            pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator)
            draft = await pipe.build_draft(
                ctx, reg, doc_artifact_id="doc-1", title="Photosynthesis Quiz", params=QuizParams(count=5, type_mix=mix)
            )
        else:
            raise
    print(f"{C_OK}Drafted '{draft.title}'  (v{draft.version}, {len(draft.payload['questions'])} questions){C_END}")
    print(f"{C_DIM}provenance: {draft.provenance['label']}  ai_generated={draft.provenance['ai_generated']}{C_END}")
    for i, q in enumerate(draft.payload["questions"], 1):
        print(f"\n  Q{i} [{q['questionType']} · bloom={q['bloom_level']}]  {q['questionText']}")
        if q.get("options"):
            for o in q["options"]:
                mark = "✓" if o["isCorrect"] else "·"
                misc = f"  {C_DIM}({o['misconception']}){C_END}" if o.get("misconception") else ""
                print(f"      {mark} {o['optionText']}{misc}")
        cite = q["citation"]
        print(f"      {C_DIM}↳ source: \"{cite['quote'][:60]}…\" @ {cite['locator']}{C_END}")
        if q.get("flags"):
            print(f"      {C_WARN}⚠ flags: {', '.join(q['flags'])}{C_END}")
    if draft.payload["warnings"]:
        print(f"\n  {C_WARN}Draft warnings: {draft.payload['warnings']}{C_END}")

    # Conversational edit
    print(f"\n{C_DIM}> \"add 2 true/false questions\"{C_END}")
    edited = await EditQuizTool(pipe, reg).run(ctx, {"draft_id": draft.id, "op": "add", "qtype": "true_false", "delta": 2})
    print(f"{C_OK}now v{edited.data['version']} with {edited.data['questions']} questions{C_END}")

    # Publish → preview → confirm
    print(f"\n{C_DIM}> \"add it to the course\"{C_END}")
    proposal = await PublishAssessmentTool(reg).run(ctx, {"draft_id": draft.id})
    print(f"{C_OK}PREVIEW — {proposal.preview.title}{C_END}")
    for line in proposal.preview.summary_lines:
        print(f"   • {line}")
    for w in proposal.preview.warnings:
        print(f"   {C_WARN}⚠ {w}{C_END}")
    print(f"   {C_DIM}content_hash={proposal.content_hash[:16]}…  writes-so-far={mookit.write_calls}{C_END}")
    action_id = harness.propose(ctx, proposal)
    await harness.confirm(action_id, current_hash=proposal.content_hash)
    print(f"{C_OK}CONFIRMED → mooKIT writes: {mookit.write_calls}{C_END}")


async def demo_announcement(ctx, reg, mookit, harness) -> None:
    h("FLOW 2 — Announcement  (\"Cancel today's class and email everyone\")")
    d = await DraftAnnouncementTool(reg).run(ctx, {"intent": "Cancel today's class and email everyone", "audience": "all"})
    print(f"{C_OK}Draft:{C_END} {json.dumps(d.data, indent=2)}")
    proposal = await SendAnnouncementTool(reg).run(ctx, {"draft_id": d.artifact_id})
    p = proposal.preview
    print(f"\n{C_OK}PREVIEW — {p.title}{C_END}")
    print(f"   To: {p.audience}")
    for line in p.summary_lines:
        print(f"   • {line}")
    print(f"   body: {p.body_markdown}")
    print(f"   {C_DIM}payload has no resolved recipient ids: sectionIds present? {'sectionIds' in proposal.payload}{C_END}")
    before = list(mookit.write_calls)
    aid = harness.propose(ctx, proposal)
    await harness.confirm(aid, current_hash=proposal.content_hash)
    print(f"{C_OK}CONFIRMED → new writes: {mookit.write_calls[len(before):]}{C_END}")


async def demo_lecture(ctx, reg, mookit, harness) -> None:
    h("FLOW 3 — Lecture  (\"Publish this under Week 4 on Monday\")")
    d = await DraftLectureTool(mookit, reg).run(
        ctx, {"week_label": "Week 4", "file_artifact_id": "art_video_1", "release_on": 1893456000}
    )
    print(f"{C_OK}{d.message}{C_END}  {C_DIM}(week_id={d.data['week_id']}){C_END}")
    proposal = await PublishLectureTool(reg).run(ctx, {"draft_id": d.artifact_id})
    print(f"\n{C_OK}PREVIEW — {proposal.preview.title}{C_END}  (diff/change-summary)")
    for row in proposal.preview.diff or []:
        print(f"   {row['field']:12} → {row['after']}")
    before = list(mookit.write_calls)
    aid = harness.propose(ctx, proposal)
    await harness.confirm(aid, current_hash=proposal.content_hash)
    print(f"{C_OK}CONFIRMED → new writes: {mookit.write_calls[len(before):]}{C_END}")


async def demo_redteam(ctx, reg) -> None:
    h("SECURITY — Injection red-team (model is fully compromised and tries to publish)")
    mookit = FakeMooKitClient()
    seed = Artifact(
        id="", type="announcement_draft", title="x", status="draft",
        payload={"title": "x", "description": "y", "type": "urgent", "notify_mail": True, "audience_intent": "all"},
        provenance=stamp(ai_generated=True, edited_by_human=False, source_ids=[]),
    )
    did = await reg.add(ctx, seed)
    registry = ToolRegistry()
    registry.register(SendAnnouncementTool(reg))
    llm = ScriptedLLM([tool_round(name="send_announcement", call_id="c", arguments={"draft_id": did}, response_id="r") for _ in DEFAULT_CASES])
    orch = Orchestrator(llm=llm, registry=registry, sessions=InMemorySessionStore(), artifacts=reg, resolver=ReferenceResolver(reg), mookit=mookit)
    report = await run_redteam(orch, ctx, DEFAULT_CASES, write_probe=lambda: len(mookit.write_calls))
    for det in report.details:
        print(f"   case '{det['case']}': direct_writes={det['direct_writes']}  pending_confirmation={det['pending_confirmation']}")
    status = f"{C_OK}PASS{C_END}" if report.passed else f"{C_WARN}FAIL{C_END}"
    print(f"\n   unconfirmed_actions = {report.unconfirmed_actions}   → {status}")


async def main(live: bool) -> None:
    ctx = _ctx()
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)
    await demo_quiz(ctx, reg, mookit, harness, live)
    await demo_announcement(ctx, reg, mookit, harness)
    await demo_lecture(ctx, reg, mookit, harness)
    await demo_redteam(_ctx(), InMemoryArtifactRegistry())
    print(f"\n{C_OK}Done.{C_END} Nothing was published until an explicit confirm; every quiz question is cited.\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the real OpenAI generator (needs OPENAI_API_KEY)")
    args = ap.parse_args()
    asyncio.run(main(args.live))
