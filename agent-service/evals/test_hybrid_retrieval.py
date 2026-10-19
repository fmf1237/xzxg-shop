import json

from hybrid_retrieval import hybrid_search, rrf
from improved_retrieval import retrieve
from query_parser import catalog_metadata, parse_query
from run_hybrid_comparison import BASELINE, LESSON06, compare
from run_retrieval_eval import load_data
from semantic_retrieval import MockEmbedder, SemanticIndex


PRODUCTS, CASES = load_data()
META = catalog_metadata(PRODUCTS)
INDEX = SemanticIndex(PRODUCTS, MockEmbedder())


def test_rrf_deduplicates_and_combines_ranks():
    ids, scores = rrf(["a", "b"], ["b", "c"])
    assert ids[0] == "b"
    assert len(ids) == 3
    assert scores["b"] > scores["a"]


def test_soft_need_never_filters_hard_qualified_candidates():
    parsed = parse_query("迅步轻便运动鞋", META)
    ids, trace = retrieve(PRODUCTS, parsed, k=12)
    assert {"s01", "s02", "s06"} <= set(ids)
    assert ids[0] == "s01"
    assert not any(item["id"] == "s02" for item in trace["filtered"])


def test_hybrid_stages_and_hard_filter():
    parsed = parse_query("迅步运动鞋预算300元", META)
    ids, trace = hybrid_search(PRODUCTS, parsed, "迅步运动鞋预算300元", INDEX, rerank=True)
    assert ids == ["s01"]
    assert trace["keyword"] and trace["vector"] and trace["fusion"] and trace["filter"] and trace["rerank"]
    assert any(item["id"] == "s02" and "over_budget" in item["reasons"] for item in trace["filter"])
    assert trace["embedding_kind"] == "mock_lexical_hash"


def test_comparison_keeps_mock_separate_and_frozen_reports():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    sixth = json.loads(LESSON06.read_text(encoding="utf-8"))
    report = compare(PRODUCTS, CASES, baseline, sixth, MockEmbedder())
    assert report["evidence_level"] == "mock_protocol_only"
    assert len(report["cases"]) == 30
    assert report["summary"]["keyword_baseline"]["recall_at_k"] == baseline["summary"]["recall_at_k"]
    assert report["summary"]["keyword_baseline"]["mean_query_ms"] is None
