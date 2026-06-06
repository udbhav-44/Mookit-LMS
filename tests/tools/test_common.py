"""B1.5 acceptance — taxonomy match / no-match candidates / who-am-i."""

from app.tools.common import PermissionIntrospectTool, ResolveTaxonomyTool, WhoAmITool
from tests.fakes.fake_mookit import FakeMooKitClient


async def test_resolve_taxonomy_exact_match(ctx) -> None:
    tool = ResolveTaxonomyTool(FakeMooKitClient())
    result = await tool.run(ctx, {"type": "week", "label": "Week 4"})
    assert result.ok
    assert result.data["matched"] == 104
    assert result.data["matched_title"] == "Week 4"


async def test_resolve_taxonomy_case_insensitive(ctx) -> None:
    tool = ResolveTaxonomyTool(FakeMooKitClient())
    result = await tool.run(ctx, {"type": "week", "label": "  week 4 "})
    assert result.data["matched"] == 104


async def test_resolve_taxonomy_no_match_returns_candidates(ctx) -> None:
    tool = ResolveTaxonomyTool(FakeMooKitClient())
    result = await tool.run(ctx, {"type": "week", "label": "Week 99"})
    assert result.data["matched"] is None
    assert len(result.data["candidates"]) == 4


async def test_whoami(ctx) -> None:
    result = await WhoAmITool(FakeMooKitClient()).run(ctx, {})
    assert result.ok
    assert result.data["id"] == ctx.user_id


async def test_my_permissions(ctx) -> None:
    result = await PermissionIntrospectTool().run(ctx, {})
    assert result.ok
    assert "assessments" in result.data
