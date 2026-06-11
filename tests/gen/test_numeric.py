"""Phase 2 — sandboxed numeric evaluation + answer verification."""

import math

import pytest

from app.gen.quiz.numeric import UnsafeExpression, safe_eval, verify_numeric


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


def test_verify_numeric_match() -> None:
    res = verify_numeric(
        solution_expr="0.5 * m * v**2",
        variables={"m": 2.0, "v": 3.0},
        stated_answer=9.0,
        expected_unit="J",
        stated_unit="joules",
    )
    assert res.ok and res.matches and res.unit_ok
    assert res.computed == pytest.approx(9.0)


def test_verify_numeric_answer_mismatch() -> None:
    res = verify_numeric(solution_expr="m * a", variables={"m": 2, "a": 5}, stated_answer=12.0)
    assert not res.ok and not res.matches
    assert "mismatch" in res.reason


def test_verify_numeric_unit_mismatch() -> None:
    res = verify_numeric(
        solution_expr="m * a", variables={"m": 2, "a": 5}, stated_answer=10.0,
        expected_unit="N", stated_unit="kg",
    )
    assert not res.ok and res.matches and not res.unit_ok
    assert "unit" in res.reason


def test_verify_numeric_unsafe_expression_is_not_ok() -> None:
    res = verify_numeric(solution_expr="os.system('x')", variables={}, stated_answer=0.0)
    assert not res.ok and res.computed is None
