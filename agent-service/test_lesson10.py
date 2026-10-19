"""验证脚本的离线判定测试；不访问真实 LLM 或 Go API。"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from verify_real_llm_e2e import check_case, mentions_price  # noqa: E402


@pytest.mark.parametrize("answer", [
    "价格是 129 元", "￥129.00", "¥ 129.00", "129.00 元",
    "价格：129.00", "价格: 129.00", "售价:129.00", "售价： 129.00",
])
def test_price_comparison_accepts_format_variants(answer):
    assert mentions_price(answer, "129.00")


@pytest.mark.parametrize("answer", [
    "价格：399.00", "售价:399.00", "库存 129 件", "库存：129.00",
    "型号 Mouse 129.00", "Token 数量：129", "共消耗 129 Tokens", "Quiet Mouse S，库存充足",
    "价格：129.001", "售价: 129.00.5", "¥129.00.5",
])
def test_price_comparison_rejects_other_numbers(answer):
    assert not mentions_price(answer, "129.00")


def test_detail_requires_grounded_observations():
    item = {"id": "p_mouse_001", "name": "Quiet Mouse S", "price": "129.00", "stock_quantity": 120}
    trace = [
        {"observation": {"tool": "search_products", "status": "ok", "result": [{"id": item["id"], "name": item["name"], "price": item["price"]}]}},
        {"observation": {"tool": "get_product_detail", "status": "ok", "result": item}},
    ]
    good = [{"type": "final", "text": "Quiet Mouse S：129 元，库存 120 件。"}]
    bad = [{"type": "final", "text": "Quiet Mouse S：399 元，库存 120 件。"}]
    assert check_case("detail", good[0]["text"], "ok", trace, good) == []
    assert "最终回答缺少详情中的 price" in check_case("detail", bad[0]["text"], "ok", trace, bad)


def test_missing_and_error_need_honest_final():
    empty = [{"observation": {"tool": "search_products", "status": "empty", "result": []}}]
    assert check_case("missing", "没有找到商品", "ok", empty, [{"type": "final", "text": "没有找到商品"}]) == []
    assert check_case("missing", "为你找到 99 元商品", "ok", empty, [{"type": "final", "text": "为你找到 99 元商品"}])
    error = [{"observation": {"tool": "search_products", "status": "error", "result": None}}]
    assert check_case("tool_error", "服务暂时不可用", "tool_error", error, [{"type": "final", "text": "服务暂时不可用"}]) == []
    assert check_case("tool_error", "查到了 Mouse", "tool_error", error, [{"type": "final", "text": "查到了 Mouse"}])
