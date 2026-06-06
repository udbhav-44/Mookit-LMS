"""B0.1 — strict JSON-Schema dialect for tool params + structured outputs.

OpenAI strict mode requires, recursively:
  * ``additionalProperties: false`` on every object
  * EVERY property listed in ``required`` (optionals are modeled as ``["type", "null"]``)
  * ``$defs`` inlined-by-ref is fine; recursion via ``$ref: "#"``.

Pydantic's ``model_json_schema`` is close but (a) only marks truly-required fields as required and
(b) omits ``additionalProperties``. ``strict_schema`` post-processes it to satisfy strict mode.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return an OpenAI strict-mode JSON Schema for ``model``'s fields."""
    schema = model.model_json_schema()
    _strictify(schema, schema)
    return schema


def _strictify(node: Any, root: dict[str, Any]) -> None:
    """Recursively enforce strict-mode rules in place."""
    if isinstance(node, dict):
        _collapse_nullable(node)
        # Object nodes: force additionalProperties:false and required==all props.
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties")
            if isinstance(props, dict):
                node["additionalProperties"] = False
                node["required"] = list(props.keys())
                for sub in props.values():
                    _strictify(sub, root)
        # Recurse into array item schemas.
        for key in ("items", "prefixItems"):
            if key in node:
                _strictify(node[key], root)
        # $defs / definitions are mappings of name -> schema; visit each schema.
        for key in ("$defs", "definitions"):
            container = node.get(key)
            if isinstance(container, dict):
                for sub in container.values():
                    _strictify(sub, root)
        for key in ("anyOf", "oneOf", "allOf"):
            if key in node and isinstance(node[key], list):
                for sub in node[key]:
                    _strictify(sub, root)
    elif isinstance(node, list):
        for sub in node:
            _strictify(sub, root)


def _collapse_nullable(node: dict[str, Any]) -> None:
    """Collapse ``anyOf: [{"type": X}, {"type": "null"}]`` into ``{"type": [X, "null"]}``.

    Pydantic renders ``str | None`` as an ``anyOf`` with a null branch; the strict-mode dialect
    prefers the compact type-array form for simple scalar optionals.
    """
    any_of = node.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:
        return
    has_null = any(isinstance(b, dict) and b.get("type") == "null" for b in any_of)
    if not has_null:
        return
    non_null = [b for b in any_of if not (isinstance(b, dict) and b.get("type") == "null")]
    if len(non_null) == 1 and set(non_null[0].keys()) <= {"type"} and "type" in non_null[0]:
        node.pop("anyOf")
        node["type"] = [non_null[0]["type"], "null"]


def tool_schema(*, name: str, description: str, params: type[BaseModel]) -> dict[str, Any]:
    """Build an OpenAI Responses-API function-tool schema entry (strict)."""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": strict_schema(params),
    }
