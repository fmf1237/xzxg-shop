import importlib.util
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location("react_agent", Path(__file__).with_name("react_agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_one_tool_then_final():
    result = agent.run_react("推荐面霜")
    assert [step["model_output"]["type"] for step in result["trace"]] == ["tool_call", "final"]
    assert "保湿面霜" in result["answer"]


def test_two_different_tools():
    result = agent.run_react("推荐运动鞋并查看第一款详情")
    assert [step["model_output"].get("tool") for step in result["trace"]] == ["search_products", "get_product_detail", None]
    assert "轻便运动鞋" in result["answer"]


def test_observation_in_next_context():
    result = agent.run_react("推荐运动鞋并查看第一款详情")
    first_observation = result["trace"][0]["observation"]
    assert result["trace"][1]["model_input"][-1] == {"role": "tool", "content": first_observation}
    assert result["trace"][1]["model_input"][-2]["role"] == "assistant"


def test_tool_failure_and_recovery():
    def broken(**kwargs):
        raise OSError("模拟断线")

    result = agent.run_react("推荐面霜", tools={"search_products": broken})
    assert result["trace"][0]["observation"]["status"] == "error"
    assert result["trace"][1]["model_output"]["type"] == "final"
    assert "模拟断线" in result["answer"]


def test_unknown_tool():
    class Unknown:
        def decide(self, messages):
            if messages[-1]["role"] == "tool":
                return {"type": "final", "text": messages[-1]["content"]["message"]}
            return {"type": "tool_call", "tool": "missing", "arguments": {}}

    result = agent.run_react("推荐面霜", llm=Unknown())
    assert result["trace"][0]["observation"]["status"] == "error"
    assert "未知工具" in result["answer"]


@pytest.mark.parametrize("action", [None, {}, {"type": "tool_call", "tool": "search_products", "arguments": "bad"}, {"type": "final", "text": ""}])
def test_invalid_action(action):
    class Invalid:
        def decide(self, messages):
            return action

    assert agent.run_react("你好", llm=Invalid())["error"] == "invalid_action"


def test_max_steps():
    class Repeater:
        def decide(self, messages):
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "面霜"}}

    result = agent.run_react("推荐面霜", llm=Repeater(), max_steps=2)
    assert result["error"] == "max_steps_exceeded"
    assert len(result["trace"]) == 2


def test_direct_final():
    result = agent.run_react("你好")
    assert result["error"] is None
    assert len(result["trace"]) == 1
    assert result["trace"][0]["model_output"]["type"] == "final"


def test_empty_result_and_bad_arguments():
    empty = agent.run_react("推荐无人机")
    assert empty["trace"][0]["observation"]["status"] == "empty"
    assert "没有找到" in empty["answer"]

    class BadArguments:
        def decide(self, messages):
            if messages[-1]["role"] == "tool":
                return {"type": "final", "text": messages[-1]["content"]["message"]}
            return {"type": "tool_call", "tool": "get_product_detail", "arguments": {"product_id": 1}}

    bad = agent.run_react("查看商品", llm=BadArguments())
    assert bad["trace"][0]["observation"]["status"] == "error"
    assert "参数错误" in bad["answer"]
