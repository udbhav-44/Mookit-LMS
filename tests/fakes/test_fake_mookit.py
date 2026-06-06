"""FakeMooKitClient acceptance — conforms to canonical client, seeds Week 4, records calls."""

from app.contracts.mookit import MooKitClient
from tests.fakes.fake_mookit import FakeMooKitClient


def test_satisfies_contract() -> None:
    assert isinstance(FakeMooKitClient(), MooKitClient)


async def test_taxonomy_includes_week_4(ctx) -> None:
    weeks = await FakeMooKitClient().list_taxonomy(ctx, "week")
    assert "Week 4" in [t.name for t in weeks]


async def test_permissions_grant_phase1(ctx) -> None:
    pm = await FakeMooKitClient().get_permissions(ctx)
    assert pm.has_permission("assessments", "publish")
    assert pm.has_permission("announcements", "publish")
    assert pm.has_permission("lectures", "create")


async def test_records_calls(ctx) -> None:
    client = FakeMooKitClient()
    await client.users_me(ctx)
    await client.list_taxonomy(ctx, "week")
    assert [m for (m, _kw) in client.calls] == ["users_me", "list_taxonomy"]


async def test_write_calls_tracked(ctx) -> None:
    from app.mookit.schemas import AnnouncementCreate

    client = FakeMooKitClient()
    await client.create_announcement(ctx, AnnouncementCreate(title="x", type="normal", notifyMail=0, published={"status": 1}))
    assert client.write_calls == ["create_announcement"]
