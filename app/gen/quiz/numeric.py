"""Phase 2 — deterministic numeric verification for quantitative engineering items.

Engineering quizzes need numeric answers that are actually *correct*, and LLMs make arithmetic
mistakes. So for a quantitative item the generator emits a solution as a checkable expression plus the
input values; we recompute it here and confirm the stated answer matches within tolerance. The answer
is grounded in the source's formulas/values — not trusted from the model's mental arithmetic.

Evaluation is a sandboxed AST walk (no ``eval``/``exec``, no new dependency): only numeric literals,
the named input variables, parentheses, the arithmetic operators (+ - * / // % **, unary ±), and a
small whitelist of math functions/constants are allowed. Anything else raises ``UnsafeExpression`` —
attribute access, calls to non-whitelisted names, comprehensions, etc. are all rejected.

Unit checking is a light normalized string compare (not full dimensional analysis); a mismatch is
reported but never silently ignored.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from pydantic import BaseModel


class UnsafeExpression(ValueError):
    """Raised when an expression uses a construct outside the numeric whitelist."""


_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "log": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
    "abs": abs, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil,
    "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot,
    "round": round, "pow": math.pow,
}
_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def safe_eval(expr: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate a numeric expression against ``variables``. Raises ``UnsafeExpression`` if the
    expression strays outside the arithmetic whitelist."""
    variables = variables or {}
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:  # noqa: TRY003
        raise UnsafeExpression(f"could not parse: {exc}") from exc
    return float(_eval(tree.body, variables))


def _eval(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpression(f"non-numeric constant: {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return float(env[node.id])
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise UnsafeExpression(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise UnsafeExpression(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp):
        uop = _UNARY_OPS.get(type(node.op))
        if uop is None:
            raise UnsafeExpression(f"unary operator not allowed: {type(node.op).__name__}")
        return uop(_eval(node.operand, env))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise UnsafeExpression("only whitelisted math functions may be called")
        if node.keywords:
            raise UnsafeExpression("keyword arguments not allowed")
        args = [_eval(a, env) for a in node.args]
        return float(_FUNCS[node.func.id](*args))
    raise UnsafeExpression(f"disallowed expression: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class NumericResult(BaseModel):
    ok: bool                  # True iff computed value matches the stated answer within tolerance
    computed: float | None    # recomputed value (None if the expression could not be evaluated)
    matches: bool             # value match (ignoring units)
    unit_ok: bool             # stated unit matches expected unit (after normalization)
    reason: str               # human-readable explanation for flags/review


def _normalize_unit(u: str | None) -> str:
    if not u:
        return ""
    s = u.strip().lower().replace("·", " ").replace("*", " ")
    aliases = {
        "metres": "m", "meter": "m", "meters": "m", "metre": "m",
        "seconds": "s", "second": "s", "sec": "s",
        "newtons": "n", "newton": "n",
        "kilograms": "kg", "kilogram": "kg",
        "pascals": "pa", "pascal": "pa",
        "joules": "j", "joule": "j",
    }
    return " ".join(aliases.get(tok, tok) for tok in s.split())


def verify_numeric(
    *,
    solution_expr: str,
    variables: dict[str, float],
    stated_answer: float,
    rel_tol: float = 1e-3,
    abs_tol: float = 1e-9,
    expected_unit: str | None = None,
    stated_unit: str | None = None,
) -> NumericResult:
    """Recompute ``solution_expr`` from ``variables`` and check it equals ``stated_answer``.

    Returns ``ok=True`` only when both the value matches within tolerance AND the units agree.
    """
    try:
        computed = safe_eval(solution_expr, variables)
    except UnsafeExpression as exc:
        return NumericResult(
            ok=False, computed=None, matches=False, unit_ok=False,
            reason=f"unsafe/unevaluable solution expression: {exc}",
        )
    matches = math.isclose(computed, stated_answer, rel_tol=rel_tol, abs_tol=abs_tol)
    unit_ok = _normalize_unit(expected_unit) == _normalize_unit(stated_unit)
    if matches and unit_ok:
        reason = "verified"
    elif not matches:
        reason = f"answer mismatch: computed {computed:g} but key states {stated_answer:g}"
    else:
        reason = f"unit mismatch: expected '{expected_unit}', key states '{stated_unit}'"
    return NumericResult(ok=matches and unit_ok, computed=computed, matches=matches, unit_ok=unit_ok, reason=reason)
