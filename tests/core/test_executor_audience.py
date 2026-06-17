"""H2 — announcement audience resolution must never silently broadcast to all students.

A specific section that cannot be verified (lookup failure) or does not match any course
section must RAISE, not fall back to "all students". Only an explicit "all" intent → None.
"""

import pytest

from app.core.executor import DeterministicExecutor
from tests.fakes.fake_mookit import FakeMooKitClient


def _executor() -> DeterministicExecutor:
    return DeterministicExecutor(FakeMooKitClient())


async def test_all_students_resolves_to_none(ctx) -> None:
    ex = _executor()
    for intent in ("all", "everyone", "all students", "", "  All Students  "):
        assert await ex._resolve_audience(ctx, intent) is None


async def test_known_section_resolves_to_ids(ctx) -> None:
    ex = _executor()
    # Fake taxonomy exposes "Section 1".."Section 3" with ids 401..403.
    assert await ex._resolve_audience(ctx, "Section 3") == [403]


async def test_unknown_section_refuses_instead_of_broadcasting(ctx) -> None:
    ex = _executor()
    with pytest.raises(ValueError, match="didn't match any course section"):
        await ex._resolve_audience(ctx, "Section 99")


async def test_taxonomy_lookup_failure_refuses(ctx, monkeypatch) -> None:
    ex = _executor()

    async def _boom(_ctx, _type):
        raise RuntimeError("mooKIT down")

    monkeypatch.setattr(ex.mookit, "list_taxonomy", _boom)
    with pytest.raises(ValueError, match="Refusing to broadcast"):
        await ex._resolve_audience(ctx, "Section 1")
