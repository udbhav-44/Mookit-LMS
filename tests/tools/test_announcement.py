"""B3.2 acceptance — no recipient ids; channel inference; sanitization; propose-not-execute."""

from app.contracts import ProposedAction, ToolResult
from app.tools.announcement import DraftAnnouncementTool, SendAnnouncementTool
from tests.fakes.fake_stores import InMemoryArtifactRegistry


async def _draft(ctx, reg, intent, audience="all"):
    res = await DraftAnnouncementTool(reg).run(ctx, {"intent": intent, "audience": audience})
    assert isinstance(res, ToolResult)
    return res.artifact_id


async def test_urgent_and_email_inference(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _draft(ctx, reg, "Cancel today's class and email everyone")
    draft = await reg.get(ctx, aid)
    assert draft.payload["type"] == "urgent"
    assert draft.payload["notify_mail"] is True


async def test_normal_lms_only(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _draft(ctx, reg, "Reading for next week is chapter 3")
    draft = await reg.get(ctx, aid)
    assert draft.payload["type"] == "normal"
    assert draft.payload["notify_mail"] is False


async def test_send_proposes_with_audience_intent_not_ids(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _draft(ctx, reg, "Deadline extended", audience="Section 3")
    result = await SendAnnouncementTool(reg).run(ctx, {"draft_id": aid})
    assert isinstance(result, ProposedAction)
    # Audience is an intent (magic key), resolved server-side by the executor — never a recipient id.
    assert result.payload["_audience_intent"] == "Section 3"
    assert "sectionIds" not in result.payload
    assert "recipients" not in result.payload


async def test_send_sanitizes_body(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _draft(ctx, reg, "Visit http://evil.example for details")
    result = await SendAnnouncementTool(reg).run(ctx, {"draft_id": aid})
    assert "http" not in result.payload["description"]
