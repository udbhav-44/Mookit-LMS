"""Sandboxed numeric expression evaluation.

Evaluation is a sandboxed AST walk (no ``eval``/``exec``, no new dependency): only numeric literals,
named input variables, parentheses, the arithmetic operators (+ - * / // % **, unary ±), and a small
whitelist of math functions/constants are allowed. Anything else raises ``UnsafeExpression`` —
attribute access, calls to non-whitelisted names, comprehensions, etc. are all rejected.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable


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
