import json

from improved_retrieval import retrieve
from query_parser import catalog_metadata, parse_query
from run_retrieval_comparison import BASELINE, compare
from run_retrieval_eval import load_data


PRODUCTS, CASES = load_data()
META = catalog_metadata(PRODUCTS)


def search(query):
    return retrieve(PRODUCTS, parse_query(query, META))


def test_synonym_and_vague_chain():
    assert search("跑鞋")[0][:2] == ["s02", "s06"]
    assert search("夏天通勤穿的鞋")[0][:2] == ["s01", "s03"]
    assert search("无人机")[0] == []


def test_hard_constraints_before_top_k():
    result, trace = search("迅步运动鞋预算300元")
    assert result == ["s01"]
    assert any(item["id"] == "s03" and "brand_mismatch" in item["reasons"] for item in trace["filtered"])
    assert any(item["id"] == "s02" and "over_budget" in item["reasons"] for item in trace["filtered"])
    assert trace["final_ids"] == result


def test_conflict_and_no_match():
    result, trace = search("迅步和飞跃运动鞋")
    assert result == []
    assert trace["stop_reason"] == "conflicting_or_invalid_hard_constraint"
    assert search("敏感肌面霜预算200元")[0] == []


def test_comparison_uses_raw_queries_and_preserves_baseline():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = compare(PRODUCTS, CASES, baseline)
    assert len(report["cases"]) == 30
    assert report["baseline_summary"]["recall_at_k"] == baseline["summary"]["recall_at_k"]
    assert report["improved_summary"]["recall_at_k"] >= report["baseline_summary"]["recall_at_k"]
    assert not report["regressions"]
    assert {row["case_id"] for row in report["focus_cases"]} == {"c13", "c17", "c21", "c22", "c24"}
