import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("minimal_agent", Path(__file__).with_name("minimal_agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_product_recommendation():
    result = agent.run_agent("推荐运动鞋")
    assert "轻便运动鞋" in result["answer"]
    assert "缓震运动鞋" in result["answer"]
    assert [step["stage"] for step in result["steps"]] == ["plan", "tool", "answer"]


def test_budget_recommendation():
    result = agent.run_agent("推荐运动鞋，预算 200 元")
    assert result["steps"][0]["output"]["max_price"] == 200
    assert [item["id"] for item in result["steps"][1]["output"]] == ["p1"]


def test_missing_product():
    result = agent.run_agent("推荐无人机")
    assert result["steps"][1]["output"] == []
    assert "没有找到" in result["answer"]


def test_chat():
    result = agent.run_agent("你好")
    assert result["error"] is None
    assert [step["stage"] for step in result["steps"]] == ["plan", "answer"]


@pytest.mark.parametrize("value", ["", "  ", None, "推荐运动鞋，预算 0 元", "推荐运动鞋，预算 abc 元"])
def test_invalid_input(value):
    assert agent.run_agent(value)["error"] is not None


@pytest.mark.parametrize("value", [0, -1, "200", True])
def test_invalid_tool_budget(value):
    with pytest.raises(ValueError):
        agent.search_products("运动鞋", value)


def test_unknown_action(monkeypatch):
    monkeypatch.setattr(agent, "plan", lambda _: {"action": "unknown"})
    assert "未知动作" in agent.run_agent("任意输入")["error"]


def test_tool_failure(monkeypatch):
    def fail(**_):
        raise OSError("模拟故障")

    monkeypatch.setattr(agent, "search_products", fail)
    result = agent.run_agent("推荐运动鞋")
    assert result["error"] == "商品搜索工具执行失败"
    assert result["steps"][1]["stage"] == "tool"
    assert result["steps"][1]["error"] == "模拟故障"
