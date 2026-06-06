"""B1.3 acceptance — single resolve, ambiguity→confirm, type-mismatch, manifest formatting."""

from app.contracts.types import Artifact
from app.core.reference_resolver import ReferenceResolver
from tests.fakes.fake_stores import InMemoryArtifactRegistry


def _art(type_: str, title: str) -> Artifact:
    return Artifact(id="", type=type_, title=title, status="draft")


async def test_single_candidate_resolves(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await reg.add(ctx, _art("assessment_draft", "Ch3 Quiz"))
    res = await ReferenceResolver(reg).resolve(ctx, "make that one harder")
    assert res.artifact_id == aid
    assert res.confidence >= 0.8
    assert res.needs_confirmation is False


async def test_ambiguous_same_type_requests_confirmation(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    await reg.add(ctx, _art("assessment_draft", "Quiz A"))
    await reg.add(ctx, _art("assessment_draft", "Quiz B"))
    res = await ReferenceResolver(reg).resolve(ctx, "edit the quiz")
    assert res.needs_confirmation is True
    assert res.artifact_id is None
    assert len(res.candidates) == 2
    assert res.confirm_prompt and "Quiz" in res.confirm_prompt


async def test_type_mismatch_no_false_match(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    await reg.add(ctx, _art("assessment_draft", "Ch3 Quiz"))
    res = await ReferenceResolver(reg).resolve(ctx, "send that announcement")
    assert res.artifact_id is None
    assert res.needs_confirmation is True


async def test_manifest_recent_first(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    await reg.add(ctx, _art("uploaded_file", "lecture.pdf"))
    await reg.add(ctx, _art("assessment_draft", "Ch3 Quiz"))
    manifest = await ReferenceResolver(reg).manifest(ctx)
    lines = manifest.splitlines()
    # Most-recent (the quiz) appears before the earlier file.
    assert "Ch3 Quiz" in lines[0]
    assert "lecture.pdf" in lines[1]


async def test_manifest_empty(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    assert "no artifacts" in (await ReferenceResolver(reg).manifest(ctx)).lower()
