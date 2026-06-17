"""Sandboxed numeric expression evaluation."""

import math

import pytest

from app.gen.quiz.numeric import UnsafeExpression, safe_eval


def test_safe_eval_arithmetic() -> None:
    assert safe_eval("2 + 3 * 4") == 14.0
    assert safe_eval("(2 + 3) * 4") == 20.0
    assert safe_eval("2 ** 10") == 1024.0
    assert safe_eval("-5 + 2") == -3.0


def test_safe_eval_variables_and_functions() -> None:
    assert safe_eval("m * a", {"m": 2.0, "a": 9.81}) == pytest.approx(19.62)
    assert safe_eval("sqrt(x)", {"x": 16}) == 4.0
    assert safe_eval("2 * pi * r", {"r": 1}) == pytest.approx(2 * math.pi)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('x')",
        "os.system('x')",
        "(lambda: 1)()",
        "[i for i in range(3)]",
        "open('f')",
        "unknown_var + 1",
        "eval('1+1')",
    ],
)
def test_safe_eval_rejects_unsafe(expr: str) -> None:
    with pytest.raises(UnsafeExpression):
        safe_eval(expr)
