"""B0.1 acceptance — strict_schema satisfies OpenAI strict-mode rules."""

from pydantic import BaseModel

from app.llm.schema import strict_schema, tool_schema


class Inner(BaseModel):
    label: str
    weight: float


class Params(BaseModel):
    query: str
    count: int
    note: str | None = None
    inner: Inner


def _walk_objects(schema: dict):
    """Yield every object-type node (with properties) in the schema tree."""
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "properties" in node:
                yield node
            stack.extend(v for v in node.values() if isinstance(v, dict | list))
        elif isinstance(node, list):
            stack.extend(node)


def test_all_objects_have_additional_properties_false() -> None:
    schema = strict_schema(Params)
    objs = list(_walk_objects(schema))
    assert objs, "expected at least the root + nested object"
    for obj in objs:
        assert obj["additionalProperties"] is False


def test_required_equals_all_properties() -> None:
    schema = strict_schema(Params)
    for obj in _walk_objects(schema):
        assert set(obj["required"]) == set(obj["properties"].keys())


def test_nullable_renders_as_type_array() -> None:
    schema = strict_schema(Params)
    note = schema["properties"]["note"]
    assert note.get("type") == ["string", "null"]
    assert "anyOf" not in note


def test_nested_model_inlined_and_strict() -> None:
    schema = strict_schema(Params)
    # The nested Inner model is referenced via $defs; ensure it's strictified too.
    defs = schema.get("$defs", {})
    assert "Inner" in defs
    inner = defs["Inner"]
    assert inner["additionalProperties"] is False
    assert set(inner["required"]) == {"label", "weight"}


def test_tool_schema_shape() -> None:
    t = tool_schema(name="echo", description="echo back", params=Params)
    assert t["type"] == "function"
    assert t["name"] == "echo"
    assert t["strict"] is True
    assert t["parameters"]["additionalProperties"] is False
