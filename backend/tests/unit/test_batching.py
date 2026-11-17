import pytest

from app.providers.batching import plan_batches


def test_packs_greedily_by_token_budget_preserving_order() -> None:
    # 40+40=80, +30 would exceed 100 → new batch; 30+50+10=90 fits
    assert plan_batches([40, 40, 30, 50, 10], max_tokens=100, max_inputs=10) == [
        range(0, 2),
        range(2, 5),
    ]


def test_respects_max_inputs() -> None:
    assert plan_batches([1] * 5, max_tokens=100, max_inputs=2) == [
        range(0, 2),
        range(2, 4),
        range(4, 5),
    ]


def test_exact_budget_fits_and_empty_input_gives_no_batches() -> None:
    assert plan_batches([50, 50], max_tokens=100, max_inputs=10) == [range(0, 2)]
    assert plan_batches([], max_tokens=100, max_inputs=10) == []


def test_oversize_input_is_an_error_not_a_solo_batch() -> None:
    with pytest.raises(ValueError, match="input 1 has 101 tokens"):
        plan_batches([10, 101], max_tokens=100, max_inputs=10)
