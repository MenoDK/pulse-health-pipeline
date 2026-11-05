"""Combining ranked lists: reciprocal rank fusion and the weighted-sum baseline."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.search.fusion import rrf, weighted


def test_an_item_is_scored_by_the_sum_of_one_over_k_plus_its_rank_in_each_list() -> None:
    result = dict(rrf([["a", "b", "c"], ["b", "d"]], k=60))
    assert result["a"] == pytest.approx(1 / 61)
    assert result["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert result["d"] == pytest.approx(1 / 62)


def test_agreement_between_lists_beats_a_single_first_place() -> None:
    order = [item for item, _ in rrf([["lonely", "shared"], ["other", "shared"]])]
    assert order[0] == "shared"  # second in both lists beats first in one


def test_a_repeat_inside_one_list_counts_once() -> None:
    assert dict(rrf([["a", "a", "a", "b"]], k=60)) == {"a": pytest.approx(1 / 61), "b": pytest.approx(1 / 62)}


def test_equal_scores_are_broken_by_the_item_so_every_run_gives_the_same_order() -> None:
    assert [i for i, _ in rrf([["b"], ["a"]])] == ["a", "b"]
    assert [i for i, _ in rrf([["a"], ["b"]])] == ["a", "b"]


def test_empty_input_gives_nothing_and_a_bad_k_is_refused() -> None:
    assert rrf([]) == [] and rrf([[], []]) == []
    with pytest.raises(ValueError, match="k must"):
        rrf([["a"]], k=0)


@given(st.lists(st.integers(0, 12), max_size=10, unique=True), st.lists(st.integers(0, 12), max_size=10, unique=True))
def test_the_order_of_the_two_lists_does_not_matter(first: list[int], second: list[int]) -> None:
    assert rrf([first, second]) == rrf([second, first])


@given(st.lists(st.integers(0, 12), min_size=1, max_size=10, unique=True))
def test_one_list_alone_keeps_its_order(ranking: list[int]) -> None:
    assert [item for item, _ in rrf([ranking])] == ranking


def test_weighted_counts_a_missing_score_as_zero_and_orders_by_the_sum() -> None:
    result = dict(weighted({"a": 1.0, "b": 0.5}, {"b": 1.0, "c": 1.0}, vector_weight=0.7, lexical_weight=0.3))
    assert result == {"a": pytest.approx(0.7), "b": pytest.approx(0.65), "c": pytest.approx(0.3)}


def test_the_reason_for_rank_fusion_rescaling_one_list_flips_a_weighted_sum_and_cannot_touch_rrf() -> None:
    """Keyword scores and vector similarities have unrelated scales. A weighted sum silently depends on them; RRF cannot."""
    vector = {"semantic-match": 0.92, "keyword-match": 0.40}
    lexical = {"keyword-match": 0.8, "semantic-match": 0.1}
    top = lambda scores: weighted(vector, scores)[0][0]  # noqa: E731
    assert top(lexical) == "semantic-match"
    assert (
        top({k: v * 10 for k, v in lexical.items()}) == "keyword-match"
    )  # same ranking, different unit, different answer

    ranking_vector = sorted(vector, key=vector.__getitem__, reverse=True)
    ranking_lexical = sorted(lexical, key=lexical.__getitem__, reverse=True)
    rescaled = {k: v * 10 for k, v in lexical.items()}
    ranking_rescaled = sorted(rescaled, key=rescaled.__getitem__, reverse=True)
    assert rrf([ranking_vector, ranking_lexical]) == rrf([ranking_vector, ranking_rescaled])
