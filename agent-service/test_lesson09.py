"""第九课：并发隔离和异常传播；全部测试不访问网络。"""

from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as service_app  # noqa: E402
from product_api_tools import ProductAPITools  # noqa: E402


class ContextLLM:
    def decide(self, messages):
        question = messages[0]["content"]
        observations = [item["content"] for item in messages if item["role"] == "tool"]
        if not observations:
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": question}}
        return {"type": "final", "text": observations[-1]["result"][0]["name"]}


class ContextTools:
    def search_products(self, keyword, max_price=None):
        return [{"id": keyword, "name": keyword, "price": "1.00"}]

    def get_product_detail(self, product_id):
        return {"id": product_id, "name": product_id, "price": "1.00"}


def test_parallel_requests_have_independent_context():
    client = TestClient(service_app.create_app(llm=ContextLLM(), product_tools=ContextTools()))
    questions = [f"商品_{index}" for index in range(20)]

    def ask(question):
        return client.post("/api/agent/chat", json={"message": question}).json()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(ask, questions))
    assert len({item["request_id"] for item in results}) == len(questions)
    for question, result in zip(questions, results):
        assert result["status"] == "ok"
        assert result["answer"] == question
        assert result["trace"][0]["model_input"] == [{"role": "user", "content": question}]
        assert result["trace"][1]["model_input"][-1]["content"]["result"][0]["name"] == question
        assert question in str(result["trace"])
        assert all(other not in str(result["trace"]) for other in questions if other != question and not question.startswith(other))


class ErrorAwareLLM:
    def decide(self, messages):
        if messages[-1]["role"] == "tool":
            assert messages[-1]["content"]["status"] == "error"
            return {"type": "final", "text": "查询暂时失败"}
        return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}}


def test_real_tool_http_failures_are_observations():
    class Response:
        status_code = 500

        def json(self):
            raise ValueError("invalid JSON")

    class Session:
        def __init__(self, failure):
            self.failure = failure

        def get(self, url, params=None, timeout=None):
            assert timeout == 5
            if self.failure == "timeout":
                raise requests.Timeout("network detail must remain private")
            if self.failure == "invalid_json":
                response = Response()
                response.status_code = 200
                return response
            return Response()

    for failure, expected in (("timeout", "timeout"), ("http_500", "http_500"), ("invalid_json", "invalid_data")):
        tools = ProductAPITools(base_url="http://go.test", session=Session(failure))
        response = TestClient(service_app.create_app(mode="real", llm=ErrorAwareLLM(), product_tools=tools)).post("/api/agent/chat", json={"message": "Mouse"})
        data = response.json()
        assert response.status_code == 502
        assert data["status"] == "tool_error"
        assert data["trace"][0]["observation"]["error_code"] == expected
        assert "network detail" not in response.text
        assert "invalid JSON" not in response.text


def test_unexpected_model_error_hides_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    class BrokenLLM:
        def decide(self, messages):
            raise RuntimeError("secret-key internal stack path")

    response = TestClient(service_app.create_app(llm=BrokenLLM())).post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 502
    assert response.json()["status"] == "invalid_action"
    assert "secret-key" not in response.text
    assert "stack path" not in response.text


def test_unexpected_service_error_has_safe_envelope(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("password=hidden internal stack")

    monkeypatch.setattr(service_app, "run_react", broken)
    response = TestClient(service_app.create_app()).post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 500
    assert response.json()["status"] == "internal_error"
    assert response.json()["trace"] == []
    assert "hidden" not in response.text


def test_deployment_can_disable_trace(monkeypatch):
    monkeypatch.setenv("SHOP_AGENT_TRACE_ENABLED", "false")
    response = TestClient(service_app.create_app(llm=ContextLLM(), product_tools=ContextTools())).post("/api/agent/chat", json={"message": "Mouse"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Mouse"
    assert response.json()["trace"] == []
