"""@-tagged references: explicit artifact IDs are resolved and injected deterministically.

The instructor tags artifacts in the UI; the chat body carries their IDs. The orchestrator fetches
each by ID (tenant-scoped), injects an authoritative content-bearing developer message, and pushes
them onto the focus stack. Unknown / foreign IDs are skipped fail-closed (no error).
"""

from app.contracts import Artifact, RequestContext
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.tools.echo import EchoTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM, prose_round
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


def _make(llm: ScriptedLLM, artifacts: InMemoryArtifactRegistry) -> Orchestrator:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return Orchestrator(
        llm=llm,
        registry=registry,
        sessions=InMemorySessionStore(),
        artifacts=artifacts,
        resolver=ReferenceResolver(artifacts),
        mookit=FakeMooKitClient(),
    )


async def _drain(orch, ctx, text, *, references=None):
    return [e async for e in orch.run_turn(ctx, text, references=references)]


def _developer_blocks(llm: ScriptedLLM) -> str:
    """Concatenate all developer-message text from the first respond() call's input."""
    first_input = llm.calls[0]["input"]
    return "\n".join(i.get("content", "") for i in first_input if i.get("role") == "developer")


async def test_tagged_draft_payload_injected_and_spotlighted(ctx: RequestContext) -> None:
    artifacts = InMemoryArtifactRegistry()
    aid = await artifacts.add(
        ctx,
        Artifact(
            id="",
            type="assessment_draft",
            title="Photosynthesis quiz",
            status="draft",
            payload={"questions": [{"questionText": "What is chlorophyll?"}]},
        ),
    )
    llm = ScriptedLLM([prose_round("ok", response_id="r1")])
    orch = _make(llm, artifacts)

    await _drain(orch, ctx, "grade this", references=[aid])

    blocks = _developer_blocks(llm)
    assert "EXPLICITLY TAGGED" in blocks
    assert "Photosynthesis quiz" in blocks
    assert aid in blocks
    # Draft payload is injected verbatim, wrapped as untrusted data.
    assert "What is chlorophyll?" in blocks
    assert "BEGIN_UNTRUSTED" in blocks


async def test_tagged_file_lists_doc_id_without_dumping_bytes(ctx: RequestContext) -> None:
    artifacts = InMemoryArtifactRegistry()
    aid = await artifacts.add(
        ctx,
        Artifact(
            id="",
            type="uploaded_file",
            title="lecture.pdf",
            status="uploaded",
            payload={"filename": "lecture.pdf", "mime_type": "application/pdf"},
        ),
    )
    llm = ScriptedLLM([prose_round("ok", response_id="r1")])
    orch = _make(llm, artifacts)

    await _drain(orch, ctx, "make a quiz from this", references=[aid])

    blocks = _developer_blocks(llm)
    assert "EXPLICITLY TAGGED" in blocks
    assert f"doc_artifact_id={aid}" in blocks
    assert "lecture.pdf" in blocks
    # Uploaded files are not spotlighted (no payload bytes injected).
    assert "BEGIN_UNTRUSTED" not in blocks


async def test_tagged_reference_pushed_to_focus(ctx: RequestContext) -> None:
    artifacts = InMemoryArtifactRegistry()
    first = await artifacts.add(
        ctx, Artifact(id="", type="announcement_draft", title="A", status="draft", payload={})
    )
    second = await artifacts.add(
        ctx, Artifact(id="", type="assessment_draft", title="B", status="draft", payload={})
    )
    # `second` is most recent after add; tagging `first` should bring it to the top.
    assert (await artifacts.focus(ctx))[0] == second

    llm = ScriptedLLM([prose_round("ok", response_id="r1")])
    orch = _make(llm, artifacts)
    await _drain(orch, ctx, "send it", references=[first])

    assert (await artifacts.focus(ctx))[0] == first


async def test_unknown_reference_skipped_without_error(ctx: RequestContext) -> None:
    artifacts = InMemoryArtifactRegistry()
    llm = ScriptedLLM([prose_round("ok", response_id="r1")])
    orch = _make(llm, artifacts)

    events = await _drain(orch, ctx, "do it", references=["does-not-exist"])

    kinds = [e.event for e in events]
    assert "error" not in kinds
    assert kinds[-1] == "done"
    # No tagged block emitted when nothing resolves.
    assert "EXPLICITLY TAGGED" not in _developer_blocks(llm)


async def test_no_references_means_no_tagged_block(ctx: RequestContext) -> None:
    artifacts = InMemoryArtifactRegistry()
    llm = ScriptedLLM([prose_round("ok", response_id="r1")])
    orch = _make(llm, artifacts)

    await _drain(orch, ctx, "hello", references=None)

    assert "EXPLICITLY TAGGED" not in _developer_blocks(llm)
