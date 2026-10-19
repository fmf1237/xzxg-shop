from math import log2

import pytest

from retrieval_metrics import all_metrics, hit_at_k, mrr, ndcg_at_k, precision_at_k, recall_at_k


def test_binary_metrics_with_rank():
    actual, expected = ["x", "b", "a"], ["a", "b"]
    assert precision_at_k(actual, expected, 3) == pytest.approx(2 / 3)
    assert recall_at_k(actual, expected, 3) == 1
    assert hit_at_k(actual, expected, 1) == 0
    assert hit_at_k(actual, expected, 2) == 1
    assert mrr(actual, expected, 3) == 0.5
    assert ndcg_at_k(actual, expected, 3) == pytest.approx((1 / log2(3) + 1 / log2(4)) / (1 + 1 / log2(3)))


def test_empty_ground_truth_is_not_scored():
    assert all(value is None for value in all_metrics([], [], 3).values())
    assert all(value is None for value in all_metrics(["a"], [], 3).values())


def test_no_hits_and_short_result():
    assert all_metrics([], ["a"], 3) == {"precision_at_k": 0, "recall_at_k": 0, "hit_at_k": 0, "mrr": 0, "ndcg_at_k": 0}
    assert precision_at_k(["a"], ["a"], 3) == pytest.approx(1 / 3)


def test_invalid_k_and_duplicate_results():
    with pytest.raises(ValueError):
        hit_at_k(["a"], ["a"], 0)
    with pytest.raises(ValueError):
        mrr(["a", "a"], ["a"], 2)
