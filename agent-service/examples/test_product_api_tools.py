import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent))
from product_api_tools import ProductAPIError, ProductAPITools
from react_agent import FakeLLM, run_react


def card(product_id="p_001", name="轻便运动鞋", price="199.00"):
    return {"productId": product_id, "name": name, "price": price, "categoryId": "shoes", "stockStatus": "in_stock", "status": "active"}


def page(items, number=1, total=None, size=2):
    return {"items": items, "page": number, "page_size": size, "total": len(items) if total is None else total}


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def tools(responses, page_size=2, max_pages=3):
    session = Session(responses)
    return ProductAPITools("http://localhost:8080", session, timeout=3, page_size=page_size, max_pages=max_pages), session


def test_search_and_budget_with_all_pages():
    api, session = tools([Response(page([card(), card("p_002", "缓震运动鞋", "399.00")], total=3)), Response(page([card("p_003", "竞速运动鞋", "150.00")], number=2, total=3))])
    result = api.search_products("运动鞋", 200)
    assert [item["id"] for item in result] == ["p_001", "p_003"]
    assert result[0]["price"] == "199.00"
    assert session.calls[0] == ("http://localhost:8080/api/v1/products", {"keyword": "运动鞋", "page": 1, "page_size": 2}, 3)
    assert session.calls[1][1]["page"] == 2


def test_detail_and_404():
    api, session = tools([Response({**card(), "stockQuantity": 8, "description": "轻便"}), Response(status=404)])
    assert api.get_product_detail("p_001")["stock_quantity"] == 8
    assert session.calls[0][0].endswith("/api/v1/products/p_001")
    assert api.get_product_detail("absent") is None


def test_empty_and_500():
    api, _ = tools([Response(page([])), Response(status=500)])
    assert api.search_products("不存在") == []
    with pytest.raises(ProductAPIError) as exc:
        api.search_products("运动鞋")
    assert exc.value.code == "http_500"


def test_timeout_and_connection_failure():
    api, _ = tools([requests.Timeout(), requests.ConnectionError()])
    for expected in ("timeout", "connection_error"):
        with pytest.raises(ProductAPIError) as exc:
            api.search_products("运动鞋")
        assert exc.value.code == expected


def test_invalid_data():
    for payload in ([], {"items": [{}], "page": 1, "page_size": 2, "total": 1}, {"items": [card(price="abc")], "page": 1, "page_size": 2, "total": 1}):
        api, _ = tools([Response(payload)])
        with pytest.raises(ProductAPIError) as exc:
            api.search_products("运动鞋")
        assert exc.value.code == "invalid_data"


def test_pagination_limit_and_early_end():
    api, _ = tools([Response(page([card()], total=7))], max_pages=3)
    with pytest.raises(ProductAPIError) as exc:
        api.search_products("运动鞋")
    assert exc.value.code == "pagination_limit"
    api, _ = tools([Response(page([card(), card("p_002")], total=3)), Response(page([], number=2, total=3))])
    with pytest.raises(ProductAPIError) as exc:
        api.search_products("运动鞋")
    assert exc.value.code == "invalid_data"


def test_agent_injection_and_observation():
    api, _ = tools([Response(page([card()])), Response({**card(), "stockQuantity": 8, "description": "轻便"})])
    result = run_react("推荐运动鞋并查看第一款详情", llm=FakeLLM(), tools={"search_products": api.search_products, "get_product_detail": api.get_product_detail})
    assert [entry["observation"]["status"] for entry in result["trace"][:2]] == ["ok", "ok"]
    assert result["trace"][1]["model_input"][-1]["content"]["result"][0]["id"] == "p_001"
    assert "轻便运动鞋" in result["answer"]
