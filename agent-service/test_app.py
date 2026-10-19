"""第八课离线 HTTP 测试。"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import create_app  # noqa: E402
from product_api_tools import ProductAPITools  # noqa: E402


class ScriptedLLM:
    def decide(self, messages):
        tools = [m["content"] for m in messages if m["role"] == "tool"]
        if not tools:
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}, "call_id": "call_1"}
        if len(tools) == 1:
            assert tools[0]["status"] == "ok"
            return {"type": "tool_call", "tool": "get_product_detail", "arguments": {"product_id": tools[0]["result"][0]["id"]}, "call_id": "call_2"}
        return {"type": "final", "text": tools[-1]["result"]["name"]}


class Products:
    def search_products(self, keyword, max_price=None):
        return [{"id": "p_mouse_001", "name": "Quiet Mouse S", "price": "129.00"}]

    def get_product_detail(self, product_id):
        return {"id": product_id, "name": "Quiet Mouse S", "price": "129.00", "stock_quantity": 120}


def test_health_and_offline_chat(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app(mode="offline"))
    assert client.get("/health").json() == {"status": "ok", "mode": "offline"}
    response = client.post("/api/agent/chat", json={"message": "推荐运动鞋并查看第一款详情"})
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "ok"
    assert len(data["trace"]) == 3
    assert [r["model_output"]["type"] for r in data["trace"]] == ["tool_call", "tool_call", "final"]
    assert response.headers["X-Request-ID"] == data["request_id"]


def test_real_mode_with_mock_llm_and_tools():
    client = TestClient(create_app(mode="real", llm=ScriptedLLM(), product_tools=Products()))
    response = client.post("/api/agent/chat", json={"message": "推荐 Mouse 并查看第一款详情"})
    data = response.json()
    assert response.status_code == 200
    assert data["answer"] == "Quiet Mouse S"
    assert [r["observation"]["tool"] for r in data["trace"][:2]] == ["search_products", "get_product_detail"]
    assert data["trace"][1]["model_input"][-1]["tool_call_id"] == "call_1"
    assert data["trace"][2]["model_input"][-1]["tool_call_id"] == "call_2"


def test_go_http_adapter_with_mock_session():
    calls = []

    class Response:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Session:
        def get(self, url, params=None, timeout=None):
            calls.append((url, params, timeout))
            if params is not None:
                return Response({"items": [{"productId": "p_mouse_001", "name": "Quiet Mouse S", "price": "129.00"}], "total": 1, "page": 1, "page_size": 100})
            return Response({"productId": "p_mouse_001", "name": "Quiet Mouse S", "price": "129.00", "stockQuantity": 120})

    tools = ProductAPITools(base_url="http://go.test", session=Session())
    response = TestClient(create_app(mode="real", llm=ScriptedLLM(), product_tools=tools)).post("/api/agent/chat", json={"message": "找 Mouse 详情"})
    assert response.status_code == 200
    assert calls[0][0] == "http://go.test/api/v1/products"
    assert calls[0][1]["keyword"] == "Mouse"
    assert calls[1][0] == "http://go.test/api/v1/products/p_mouse_001"


def test_invalid_request():
    client = TestClient(create_app())
    for body in ({}, {"message": "  "}, {"message": 42}):
        response = client.post("/api/agent/chat", json=body)
        assert response.status_code == 422
        assert set(response.json()) == {"answer", "status", "trace", "request_id"}
        assert response.json()["status"] == "invalid_request"


def test_tool_failure_does_not_look_successful():
    class BrokenProducts(Products):
        def search_products(self, keyword, max_price=None):
            raise RuntimeError("HTTP 500")

    class HandlesError:
        def decide(self, messages):
            if messages[-1]["role"] == "tool":
                assert messages[-1]["content"]["status"] == "error"
                return {"type": "final", "text": "商品服务暂时不可用"}
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}}

    response = TestClient(create_app(mode="real", llm=HandlesError(), product_tools=BrokenProducts())).post("/api/agent/chat", json={"message": "找 Mouse"})
    assert response.status_code == 502
    assert response.json()["status"] == "tool_error"
    assert response.json()["trace"][0]["observation"]["status"] == "error"


def test_model_failure_and_configuration_error():
    class ModelFailure:
        def decide(self, messages):
            error = RuntimeError("timeout")
            error.code = "model_timeout"
            raise error

    response = TestClient(create_app(llm=ModelFailure())).post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 502
    assert response.json()["status"] == "model_error"
    assert response.json()["trace"][0]["error"] == "model_timeout"


def test_missing_real_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = TestClient(create_app(mode="real")).post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 503
    assert response.json()["status"] == "configuration_error"


def test_max_steps_and_invalid_action():
    class Repeats:
        def decide(self, messages):
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}}

    response = TestClient(create_app(llm=Repeats(), product_tools=Products(), max_steps=2)).post("/api/agent/chat", json={"message": "Mouse"})
    assert response.status_code == 504
    assert response.json()["status"] == "max_steps_exceeded"
    assert len(response.json()["trace"]) == 2

    class Invalid:
        def decide(self, messages):
            return {"type": "nope"}

    response = TestClient(create_app(llm=Invalid())).post("/api/agent/chat", json={"message": "Mouse"})
    assert response.status_code == 502
    assert response.json()["status"] == "invalid_action"


def test_trace_redacts_configured_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-123")

    class Echo:
        def decide(self, messages):
            return {"type": "final", "text": "test-secret-123"}

    response = TestClient(create_app(llm=Echo())).post("/api/agent/chat", json={"message": "test-secret-123"})
    assert response.status_code == 200
    assert "test-secret-123" not in response.text
    assert "[REDACTED]" in response.text


def test_empty_result_and_unknown_tool():
    class EmptyProducts(Products):
        def search_products(self, keyword, max_price=None):
            return []

    class EmptyAware:
        def decide(self, messages):
            if messages[-1]["role"] == "tool":
                assert messages[-1]["content"]["status"] == "empty"
                return {"type": "final", "text": "没有找到符合要求的商品。"}
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}}

    response = TestClient(create_app(llm=EmptyAware(), product_tools=EmptyProducts())).post("/api/agent/chat", json={"message": "找 Mouse"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    class Unknown:
        def decide(self, messages):
            if messages[-1]["role"] == "tool":
                return {"type": "final", "text": "工具不可用"}
            return {"type": "tool_call", "tool": "delete_product", "arguments": {}}

    response = TestClient(create_app(llm=Unknown())).post("/api/agent/chat", json={"message": "找 Mouse"})
    assert response.status_code == 502
    assert response.json()["status"] == "tool_error"
    assert "未知工具" in response.json()["trace"][0]["observation"]["message"]
