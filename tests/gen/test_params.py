"""B2.7 acceptance — mix-sum validation, delta application, difficulty change."""

import pytest
from pydantic import ValidationError

from app.gen.quiz.params import QuizParams


def test_default_valid() -> None:
    p = QuizParams()
    assert p.count == 5 and sum(p.type_mix.values()) == 5


def test_mix_must_sum_to_count() -> None:
    with pytest.raises(ValidationError):
        QuizParams(count=5, type_mix={"mcq_single": 3})


def test_apply_delta_updates_count() -> None:
    p = QuizParams(count=2, type_mix={"mcq_single": 2})
    p2 = p.apply_delta(qtype="true_false", delta=3)
    assert p2.count == 5
    assert p2.type_mix == {"mcq_single": 2, "true_false": 3}


def test_apply_negative_delta_drops_type() -> None:
    p = QuizParams(count=4, type_mix={"mcq_single": 2, "fib": 2})
    p2 = p.apply_delta(qtype="fib", delta=-2)
    assert "fib" not in p2.type_mix
    assert p2.count == 2


def test_with_difficulty() -> None:
    assert QuizParams().with_difficulty("hard").difficulty == "hard"
