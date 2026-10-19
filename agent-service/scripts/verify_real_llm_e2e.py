"""第十课：显式运行的真实 LLM + FastAPI + Go 商品 API 验证。"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402
from product_api_tools import ProductAPIError, ProductAPITools  # noqa: E402
from real_llm import RealLLM  # noqa: E402


CASES = (
    ("detail", "搜索 Mouse 并查看第一款详情，请给出名称、价格和库存。"),
    ("budget", "推荐价格不超过 300 元的鼠标；商品名称可能包含英文 Mouse。"),
    ("missing", "搜索 ShopPilotNoSuchProduct_9f4a，若没有商品请明确说明。"),
    ("tool_error", "搜索 Mouse，并根据商品查询结果回答。"),
)
NO_RESULT_WORDS = ("没有", "未找到", "找不到", "无匹配", "不存在", "失败", "不可用", "无法", "暂时")


def mentions_price(answer, price):
    amounts = re.findall(r"(?:¥|￥)\s*(\d+(?:\.\d+)?)(?![\d.])", answer)
    amounts += re.findall(r"(\d+(?:\.\d+)?)\s*元", answer)
    amounts += re.findall(r"(?:价格|售价)\s*[:：]\s*(\d+(?:\.\d+)?)(?![\d.])", answer)
    return any(Decimal(amount) == Decimal(price) for amount in amounts)


class RecordingLLM:
    def __init__(self, llm):
        self.llm = llm
        self.actions = []

    def decide(self, messages):
        action = self.llm.decide(messages)
        self.actions.append(action)
        return action


class FailingTools:
    """只用于错误场景；真实模型仍需根据失败 Observation 决策。"""

    def search_products(self, keyword, max_price=None):
        raise ProductAPIError("http_500", "商品接口返回 HTTP 500（故障注入）")

    def get_product_detail(self, product_id):
        raise ProductAPIError("http_500", "商品接口返回 HTTP 500（故障注入）")


def check_case(case_id, answer, status, trace, actions):
    """只根据本次工具返回值核对，不预设商品名称、价格或库存。"""
    observations = [row["observation"] for row in trace if "observation" in row]
    names = [row["tool"] for row in observations]
    raw_final = next((action["text"] for action in reversed(actions) if action.get("type") == "final"), "")
    issues = []
    if case_id == "detail":
        if len(observations) < 2 or names[:2] != ["search_products", "get_product_detail"]:
            issues.append("未按搜索→详情顺序调用工具")
        elif observations[0]["status"] != "ok" or observations[1]["status"] != "ok":
            issues.append("搜索或详情工具未成功")
        else:
            products, detail = observations[0]["result"], observations[1]["result"]
            if not products or detail["id"] != products[0]["id"]:
                issues.append("详情不是第一款搜索结果")
            for key in ("name", "stock_quantity"):
                if str(detail[key]) not in raw_final:
                    issues.append(f"最终回答缺少详情中的 {key}")
            if not mentions_price(raw_final, detail["price"]):
                issues.append("最终回答缺少详情中的 price")
    elif case_id == "budget":
        searches = [row for row in observations if row["tool"] == "search_products" and row["status"] == "ok"]
        budget_calls = [row.get("model_output", {}).get("arguments", {}).get("max_price") for row in trace if row.get("model_output", {}).get("tool") == "search_products"]
        if not any(type(price) is int and 0 < price <= 300 for price in budget_calls):
            issues.append("搜索工具未收到不超过 300 元的预算参数")
        if not searches:
            issues.append("没有成功搜索商品")
        else:
            matched = [item for row in searches for item in row["result"] if Decimal(item["price"]) <= 300]
            if not matched:
                issues.append("未召回预算内商品，无法验证推荐")
            elif not any(item["name"] in raw_final and mentions_price(raw_final, item["price"]) for item in matched):
                issues.append("回答未引用预算内工具商品的名称和价格")
            if re.search(r"\d+(?:\.\d+)?\s*元", raw_final):
                amounts = [Decimal(number) for number in re.findall(r"(\d+(?:\.\d+)?)\s*元", raw_final)]
                if any(amount > 300 for amount in amounts):
                    issues.append("回答中出现超过预算的价格")
    elif case_id == "missing":
        searches = [row for row in observations if row["tool"] == "search_products"]
        if not searches or not any(row["status"] == "empty" for row in searches):
            issues.append("未得到空搜索 Observation")
        if not any(word in raw_final for word in NO_RESULT_WORDS):
            issues.append("模型未明确说明无结果")
        if re.search(r"\d+(?:\.\d+)?\s*元", raw_final):
            issues.append("无结果回答含未经证实的价格")
    else:
        if not observations or not any(row["status"] == "error" for row in observations):
            issues.append("没有失败 Observation")
        if not any(word in raw_final for word in NO_RESULT_WORDS):
            issues.append("模型未说明工具失败，可能声称查询成功")
        if status != "tool_error":
            issues.append("HTTP 状态未标记工具失败")
    if case_id != "tool_error" and status != "ok":
        issues.append(f"HTTP Agent 状态为 {status}")
    return issues


def run_case(case_id, question, base_url, model):
    usage = []
    llm = RecordingLLM(RealLLM(model=model, usage_callback=usage.append))
    tools = FailingTools() if case_id == "tool_error" else ProductAPITools(base_url=base_url)
    client = TestClient(create_app(mode="real", llm=llm, product_tools=tools, max_steps=6))
    started = perf_counter()
    response = client.post("/api/agent/chat", json={"message": question})
    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    payload = response.json()
    trace = payload["trace"]
    issues = check_case(case_id, payload["answer"], payload["status"], trace, llm.actions)
    return {
        "case_id": case_id,
        "model": model,
        "http_status": response.status_code,
        "status": payload["status"],
        "request_id": payload["request_id"],
        "question": question,
        "tool_calls": [
            {"step": row["step"], "tool": row["model_output"]["tool"], "arguments": row["model_output"]["arguments"], "observation": row["observation"]}
            for row in trace if row.get("model_output", {}).get("type") == "tool_call" and "observation" in row
        ],
        "raw_model_final": next((action["text"] for action in reversed(llm.actions) if action.get("type") == "final"), None),
        "answer": payload["answer"],
        "latency_ms": elapsed_ms,
        "usage_by_call": usage,
        "issues": issues,
        "passed": not issues,
    }


def main():
    parser = argparse.ArgumentParser(description="显式验证真实 LLM Tool Calling，不在 pytest 中运行")
    parser.add_argument("--base-url", default=os.getenv("SHOP_API_BASE_URL"), help="已启动的 Go API URL")
    parser.add_argument("--output", type=Path, help="可选：保存本地 JSON 报告；请勿提交含真实用户数据的报告")
    args = parser.parse_args()
    model = os.getenv("OPENAI_MODEL")
    if not os.getenv("OPENAI_API_KEY") or not model:
        parser.error("需要 OPENAI_API_KEY 和 OPENAI_MODEL；真实模型验证未运行")
    if not args.base_url:
        parser.error("需要 --base-url 或 SHOP_API_BASE_URL；真实模型验证未运行")
    os.environ["SHOP_AGENT_TRACE_ENABLED"] = "true"
    report = {"ran_at_utc": datetime.now(timezone.utc).isoformat(), "model": model, "cases": []}
    for case_id, question in CASES:
        try:
            report["cases"].append(run_case(case_id, question, args.base_url, model))
        except Exception as exc:
            # 不将 SDK 异常、URL 或密钥原文写到报告。
            report["cases"].append({"case_id": case_id, "model": model, "passed": False, "issues": [f"执行中断：{type(exc).__name__}"]})
    report["passed"] = sum(case["passed"] for case in report["cases"])
    report["failed"] = len(report["cases"]) - report["passed"]
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
