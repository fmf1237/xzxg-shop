from query_parser import catalog_metadata, parse_query
from run_retrieval_eval import load_data


PRODUCTS, _ = load_data()
META = catalog_metadata(PRODUCTS)


def test_budget_expressions():
    for query in ("运动鞋预算 300 元", "运动鞋300 元以内", "运动鞋不超过 300 元"):
        parsed = parse_query(query, META)
        assert parsed["max_price"] == 300
        assert parsed["category"] == "运动鞋"


def test_catalog_brand_and_synonyms():
    parsed = parse_query("迅步跑鞋", META)
    assert parsed["brand"] == "迅步"
    assert parsed["category"] == "运动鞋"
    assert "跑步" in parsed["soft_requirements"]
    assert parse_query("防水球鞋", META)["category"] == "运动鞋"
    assert parse_query("陌生牌运动鞋", META)["brand"] is None


def test_soft_need_is_not_hard_constraint():
    parsed = parse_query("夏天通勤穿的鞋", META)
    assert parsed["category"] is None
    assert parsed["max_price"] is None
    assert {"夏季", "通勤"} <= set(parsed["soft_requirements"])
    assert "generic_footwear_not_hard" in parsed["diagnostics"]
    assert parse_query("便宜运动鞋", META)["max_price"] is None


def test_conflicts_and_invalid_budget():
    assert "conflicting_brands" in parse_query("迅步和飞跃运动鞋", META)["diagnostics"]
    assert "conflicting_budgets" in parse_query("运动鞋预算200元，不超过300元", META)["diagnostics"]
    assert "invalid_budget" in parse_query("运动鞋预算0元", META)["diagnostics"]
    assert "empty_query" in parse_query(" ", META)["diagnostics"]
