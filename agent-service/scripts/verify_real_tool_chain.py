"""显式运行：Mock LLM → FastAPI → ReAct → 真实 Go API → MySQL。"""

import argparse
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402
from product_api_tools import ProductAPITools  # noqa: E402


class ControlledLLM:
    """只控制动作；回答所用商品字段全部来自真实 Observation。"""

    def decide(self, messages):
        observations = [message["content"] for message in messages if message["role"] == "tool"]
        if not observations:
            return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": "Mouse"}}
        latest = observations[-1]
        if latest["status"] != "ok":
            return {"type": "final", "text": "商品查询失败或无结果"}
        if latest["tool"] == "search_products":
            products = latest["result"]
            item = next((product for product in products if product["id"] == "p_mouse_001"), None)
            if item is None:
                return {"type": "final", "text": "搜索结果没有目标商品"}
            return {"type": "tool_call", "tool": "get_product_detail", "arguments": {"product_id": item["id"]}}
        item = latest["result"]
        return {"type": "final", "text": f'{item["name"]}：{item["price"]} 元，库存 {item["stock_quantity"]} 件。'}


def main():
    parser = argparse.ArgumentParser(description="运行真实 Go 商品工具链；不会调用真实 LLM")
    parser.add_argument("--base-url", required=True, help="已启动的 Go API，例如 http://127.0.0.1:8080")
    args = parser.parse_args()
    tools = ProductAPITools(base_url=args.base_url)
    client = TestClient(create_app(mode="real", llm=ControlledLLM(), product_tools=tools))
    response = client.post("/api/agent/chat", json={"message": "搜索 Mouse 并查看 p_mouse_001 详情"})
    data = response.json()
    if response.status_code != 200 or data["status"] != "ok":
        raise SystemExit(f'Agent 请求失败：HTTP {response.status_code}，{data["status"]}')
    trace = data["trace"]
    if [entry.get("observation", {}).get("tool") for entry in trace] != ["search_products", "get_product_detail", None]:
        raise SystemExit("工具调用顺序不符合预期")
    search = trace[0]["observation"]["result"]
    detail = trace[1]["observation"]["result"]
    if detail["id"] != "p_mouse_001" or not any(item["id"] == detail["id"] for item in search):
        raise SystemExit("搜索与详情数据不一致")
    for field in (detail["name"], detail["price"], str(detail["stock_quantity"])):
        if field not in data["answer"]:
            raise SystemExit(f"最终回答缺少真实详情字段：{field}")
    print({"status": data["status"], "answer": data["answer"], "request_id": data["request_id"], "tool_calls": 2})


if __name__ == "__main__":
    main()
