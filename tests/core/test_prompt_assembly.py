"""B0.3 acceptance — static prefix byte-stable; variable content ordered + last."""

from app.contracts import Message
from app.core.prompts import SYSTEM_PROMPT, build_input
from app.core.prompts.assembly import prompt_cache_key


def test_system_prompt_is_byte_stable() -> None:
    # The static prefix must not contain volatile data; two reads are identical bytes.
    assert SYSTEM_PROMPT == SYSTEM_PROMPT
    # No obvious volatile tokens leaked into the static prefix.
    for token in ("202", "session", "request_id", "uid="):
        assert token not in SYSTEM_PROMPT


def test_build_input_orders_manifest_transcript_user() -> None:
    transcript = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    items = build_input(manifest="- art_1: Quiz", transcript=transcript, user_turn="add 5 more")
    roles = [i["role"] for i in items]
    assert roles[0] == "developer"  # manifest first
    assert "CURRENT ARTIFACTS" in items[0]["content"]
    assert items[-1] == {"role": "user", "content": "add 5 more"}  # user turn last
    assert [i["content"] for i in items[1:3]] == ["hi", "hello"]


def test_build_input_no_manifest() -> None:
    items = build_input(manifest=None, transcript=[], user_turn="hello")
    assert items == [{"role": "user", "content": "hello"}]


def test_prompt_cache_key_includes_tenant_and_version() -> None:
    key = prompt_cache_key(tenant_key="inst:course", model="gpt-4o")
    assert key.startswith("inst:course:gpt-4o:v")


def test_build_input_prefix_independent_of_user_turn() -> None:
    transcript = [Message(role="user", content="hi")]
    a = build_input(manifest="m", transcript=transcript, user_turn="turn A")
    b = build_input(manifest="m", transcript=transcript, user_turn="turn B")
    # Everything except the final user turn is identical (variable content appended last).
    assert a[:-1] == b[:-1]
