from run_retrieval_eval import evaluate, keyword_search, load_data, markdown_report


def test_fixture_labels_and_case_count():
    products, cases = load_data()
    assert len(cases) == 30
    by_id = {p["id"]: p for p in products}
    assert all(case["expected_product_ids"] for case in cases if case["test_type"] != "no_match")
    assert all(not case["expected_product_ids"] for case in cases if case["test_type"] == "no_match")
    assert by_id["s04"]["brand"] == "飞跃" and "防水" in by_id["s04"]["selling_points"]
    assert by_id["s01"]["price"] == "199.00"


def test_baseline_is_deterministic_and_declares_ordering():
    products, cases = load_data()
    first = evaluate(products, cases)
    assert first == evaluate(products, cases)
    assert "不代表" in first["ordering_note"]
    assert first["summary"]["no_match_cases"] == 3
    assert first["summary"]["correct_rejection_rate"] == 1.0
    assert "分页限制" in markdown_report(first)


def test_search_price_and_page_boundary():
    products, _ = load_data()
    assert keyword_search(products, "防水运动鞋", 350)[0] == ["s04"]
    assert keyword_search(products, "运动鞋", 100)[0] == []
    assert keyword_search(products, "运动鞋", page_size=2, max_pages=1)[1] == "pagination_limit"
