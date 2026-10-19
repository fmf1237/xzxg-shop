import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from react_agent import FakeLLM, run_react
from real_llm import ModelCallError, RealLLM


def response(tool=None, arguments=None, call_id="call_1", text=None, extra_calls=0):
    calls = []
    if tool:
        calls = [NS(id=call_id, type="function", function=NS(name=tool, arguments=json.dumps(arguments)))]
        calls *= 1 + extra_calls
    return NS(choices=[NS(message=NS(tool_calls=calls, content=text))])


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def llm(client):
    return RealLLM(client=client, api_key="test-only", model="mock-model")


def test_tool_call_and_schema():
    client = Client([response("search_products", {"keyword": "面霜"})])
    action = llm(client).decide([{"role": "user", "content": "推荐面霜"}])
    assert action == {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "面霜"}, "call_id": "call_1"}
    assert client.requests[0]["parallel_tool_calls"] is False
    assert {tool["function"]["name"] for tool in client.requests[0]["tools"]} == {"search_products", "get_product_detail"}


def test_direct_final():
    assert llm(Client([response(text="你好")])).decide([{"role": "user", "content": "你好"}]) == {"type": "final", "text": "你好"}


def test_tool_result_linked_and_two_calls():
    client = Client([
        response("search_products", {"keyword": "运动鞋"}, "call_search"),
        response("get_product_detail", {"product_id": "p1"}, "call_detail"),
        response(text="轻便运动鞋，199 元。"),
    ])
    result = run_react("推荐运动鞋并查看第一款详情", llm=llm(client))
    assert result["error"] is None
    assert len(client.requests) == 3
    second = client.requests[1]["messages"]
    assert second[-2]["tool_calls"][0]["id"] == "call_search"
    assert second[-1]["tool_call_id"] == "call_search"
    assert json.loads(second[-1]["content"])["result"][0]["id"] == "p1"
    third = client.requests[2]["messages"]
    assert third[-1]["tool_call_id"] == "call_detail"


def test_bad_tool_arguments_feed_back():
    client = Client([response("get_product_detail", {"product_id": 123}), response(text="参数有误")])
    result = run_react("查看商品", llm=llm(client))
    assert result["trace"][0]["observation"]["status"] == "error"
    assert "参数错误" in client.requests[1]["messages"][-1]["content"]


def test_unknown_tool_and_multiple_calls():
    client = Client([response("unknown", {}), response(text="工具不可用")])
    result = run_react("查商品", llm=llm(client))
    assert "未知工具" in result["trace"][0]["observation"]["message"]
    result = run_react("查商品", llm=llm(Client([response("search_products", {"keyword": "面霜"}, extra_calls=1)])))
    assert result["error"] == "multiple_tool_calls"


def test_invalid_model_structure_and_api_errors():
    assert run_react("你好", llm=llm(Client([response(text=None)])))["error"] == "invalid_model_response"
    for exception_name, code in [("APITimeoutError", "model_timeout"), ("APIConnectionError", "model_connection_error"), ("RateLimitError", "model_rate_limited")]:
        error_type = type(exception_name, (Exception,), {})
        assert run_react("你好", llm=llm(Client([error_type()])))["error"] == code


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ModelCallError, match="missing_api_key"):
        RealLLM(client=Client([]), model="mock-model")


def test_fake_regression_and_max_steps():
    assert run_react("推荐面霜", llm=FakeLLM())["error"] is None
    client = Client([response("search_products", {"keyword": "面霜"})])
    assert run_react("推荐面霜", llm=llm(client), max_steps=1)["error"] == "max_steps_exceeded"
