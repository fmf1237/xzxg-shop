"""二元相关性检索指标；空标准答案返回 None，由拒答率单独评估。"""

from math import log2


def _check(actual, expected, k):
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k 必须是正整数")
    if len(actual) != len(set(actual)):
        raise ValueError("结果 ID 不得重复")
    return set(expected)


def precision_at_k(actual, expected, k):
    relevant = _check(actual, expected, k)
    return sum(item in relevant for item in actual[:k]) / k if relevant else None


def recall_at_k(actual, expected, k):
    relevant = _check(actual, expected, k)
    return sum(item in relevant for item in actual[:k]) / len(relevant) if relevant else None


def hit_at_k(actual, expected, k):
    relevant = _check(actual, expected, k)
    return float(any(item in relevant for item in actual[:k])) if relevant else None


def mrr(actual, expected, k):
    relevant = _check(actual, expected, k)
    if not relevant:
        return None
    return next((1 / rank for rank, item in enumerate(actual[:k], 1) if item in relevant), 0.0)


def ndcg_at_k(actual, expected, k):
    relevant = _check(actual, expected, k)
    if not relevant:
        return None
    dcg = sum(1 / log2(rank + 1) for rank, item in enumerate(actual[:k], 1) if item in relevant)
    ideal = sum(1 / log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


def all_metrics(actual, expected, k):
    return {"precision_at_k": precision_at_k(actual, expected, k), "recall_at_k": recall_at_k(actual, expected, k), "hit_at_k": hit_at_k(actual, expected, k), "mrr": mrr(actual, expected, k), "ndcg_at_k": ndcg_at_k(actual, expected, k)}
