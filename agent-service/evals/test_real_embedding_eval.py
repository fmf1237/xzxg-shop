"""第十一课报告逻辑离线测试；不会加载或下载模型。"""

import pytest

from run_real_embedding_eval import _failure_reason, enrich_report
from semantic_retrieval import MockEmbedder


def test_real_report_rejects_mock_embedding():
    with pytest.raises(ValueError, match="Mock"):
        enrich_report({"cases": []}, [], [], MockEmbedder(), 0, 0)


def test_failure_categories_separate_candidate_filter_and_ranking():
    row = {"expected_product_ids": ["s01"], "results": {"lesson06_rule": {"ids": [], "trace": {"candidates": [], "filtered": []}}}}
    assert "未召回" in _failure_reason(row, "lesson06_rule")
    row["results"]["lesson06_rule"]["trace"]["candidates"] = ["s01"]
    assert "排序" in _failure_reason(row, "lesson06_rule")
    row["results"]["lesson06_rule"]["trace"]["filtered"] = [{"id": "s01"}]
    assert "约束过滤" in _failure_reason(row, "lesson06_rule")

    row["results"]["hybrid"] = {"ids": [], "trace": {"filter": [{"id": "s01", "kept": False}], "fusion": [{"id": "s01"}]}}
    assert "硬约束过滤" in _failure_reason(row, "hybrid")
    row["results"]["hybrid"]["trace"]["filter"][0]["kept"] = True
    assert "排序" in _failure_reason(row, "hybrid")
