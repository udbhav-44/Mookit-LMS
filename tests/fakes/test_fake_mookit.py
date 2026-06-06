"""UK.2 acceptance — FakeMooKitClient canned shapes + call recording."""

from app.contracts.mookit import MooKitClient
from tests.fakes.fake_mookit import FakeMooKitClient


def test_satisfies_protocol() -> None:
    assert isinstance(FakeMooKitClient(), MooKitClient)


async def test_taxonomy_includes_week_4(ctx) -> None:
    weeks = await FakeMooKitClient().list_taxonomy(ctx, "week")
    titles = [t.title for t in weeks]
    assert "Week 4" in titles


async def test_permissions_grant_phase1(ctx) -> None:
    pm = await FakeMooKitClient().get_permissions(ctx)
    assert pm.can("assessments", "publish")
    assert pm.can("announcements", "publish")
    assert pm.can("lectures", "create")


async def test_records_calls(ctx) -> None:
    client = FakeMooKitClient()
    await client.whoami(ctx)
    await client.list_taxonomy(ctx, "week")
    assert [m for (m, _a, _k) in client.calls] == ["whoami", "list_taxonomy"]


async def test_write_calls_tracked(ctx) -> None:
    client = FakeMooKitClient()
    await client.create_announcement(ctx, {"title": "x"})
    assert client.write_calls == ["create_announcement"]
