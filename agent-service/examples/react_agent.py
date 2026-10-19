"""第二课：用上下文驱动的 FakeLLM 演示多轮 ReAct。"""

from copy import deepcopy
import re

from minimal_agent import PRODUCTS


def search_products(keyword, max_price=None):
    """按名称或类别搜索，返回商品摘要；空列表表示业务上无匹配。"""
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("keyword 必须是非空字符串")
    if max_price is not None and (
        isinstance(max_price, bool) or not isinstance(max_price, int) or max_price <= 0
    ):
        raise ValueError("max_price 必须是正整数")
    return [
        {"id": item["id"], "name": item["name"], "price": item["price"]}
        for item in PRODUCTS
        if (keyword in item["name"] or keyword in item["category"])
        and (max_price is None or item["price"] <= max_price)
    ]


def get_product_detail(product_id):
    """按 ID 返回商品详情；不存在时返回 None。"""
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product_id 必须是非空字符串")
    return next((item.copy() for item in PRODUCTS if item["id"] == product_id), None)


class FakeLLM:
    """每轮只查看传入 messages；没有隐藏的调用次数状态。"""

    def decide(self, messages):
        question = messages[0]["content"]
        observations = [m["content"] for m in messages if m["role"] == "tool"]
        if observations:
            latest = observations[-1]
            if latest["status"] == "error":
                return {"type": "final", "text": f'工具执行失败：{latest["message"]}'}
            if latest["status"] == "empty":
                return {"type": "final", "text": "没有找到符合要求的商品。"}
            if latest["tool"] == "get_product_detail":
                item = latest["result"]
                return {"type": "final", "text": f'{item["name"]}：{item["price"]} 元，类别是{item["category"]}。'}
            items = latest["result"]
            if "详情" in question:
                return {"type": "tool_call", "tool": "get_product_detail", "arguments": {"product_id": items[0]["id"]}}
            return {"type": "final", "text": "找到商品：" + "；".join(f'{p["name"]}（{p["price"]} 元）' for p in items)}

        keyword = next((word for word in ("运动鞋", "面霜", "键盘") if word in question), None)
        if keyword is None:
            if any(word in question for word in ("推荐", "找", "买")):
                keyword = question.replace("推荐", "").replace("找", "").strip()
            else:
                return {"type": "final", "text": "你好！请告诉我想找什么商品。"}
        budget = re.search(r"预算\s*(\S+?)\s*元", question)
        if budget and (not budget.group(1).isdigit() or int(budget.group(1)) <= 0):
            return {"type": "final", "text": "预算必须是大于 0 的整数。"}
        return {"type": "tool_call", "tool": "search_products", "arguments": {"keyword": keyword, "max_price": int(budget.group(1)) if budget else None}}


def _execute(action, tools):
    name = action["tool"]
    if name not in tools:
        return {"tool": name, "status": "error", "result": None, "message": f"未知工具：{name}"}
    try:
        result = tools[name](**action["arguments"])
    except (TypeError, ValueError) as exc:
        return {"tool": name, "status": "error", "result": None, "message": f"工具参数错误：{exc}"}
    except Exception as exc:
        observation = {"tool": name, "status": "error", "result": None, "message": f"工具执行异常：{exc}"}
        if isinstance(getattr(exc, "code", None), str):
            observation["error_code"] = exc.code
        return observation
    return {"tool": name, "status": "empty" if result is None or result == [] else "ok", "result": result, "message": "无匹配结果" if result is None or result == [] else "执行成功"}


def run_react(user_input, llm=None, max_steps=5, tools=None):
    """返回 answer、trace、messages 和 error；每轮 trace 含模型输入与输出。"""
    if not isinstance(user_input, str) or not user_input.strip():
        raise ValueError("用户输入不能为空")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps 必须是正整数")
    llm = llm or FakeLLM()
    tools = tools if tools is not None else {"search_products": search_products, "get_product_detail": get_product_detail}
    messages = [{"role": "user", "content": user_input.strip()}]
    trace = []
    for step in range(1, max_steps + 1):
        model_input = deepcopy(messages)
        try:
            action = llm.decide(deepcopy(messages))
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code:
                trace.append({"step": step, "model_input": model_input, "error": code})
                return {"answer": f"模型调用失败：{code}", "trace": trace, "messages": messages, "error": code}
            # 未预料的模型异常不能把原始异常文本写入公开 Trace。
            action = {"invalid_output": "模型决策异常"}
        record = {"step": step, "model_input": model_input, "model_output": deepcopy(action)}
        if not isinstance(action, dict) or action.get("type") not in ("tool_call", "final") or (
            action.get("type") == "final" and (not isinstance(action.get("text"), str) or not action["text"].strip())
        ) or (action.get("type") == "tool_call" and (
            not isinstance(action.get("tool"), str) or not action["tool"] or not isinstance(action.get("arguments"), dict)
        )):
            record["error"] = "模型输出非法结构"
            trace.append(record)
            return {"answer": "模型输出非法结构", "trace": trace, "messages": messages, "error": "invalid_action"}
        messages.append({"role": "assistant", "content": deepcopy(action)})
        if action["type"] == "final":
            trace.append(record)
            return {"answer": action["text"], "trace": trace, "messages": messages, "error": None}
        observation = _execute(action, tools)
        record["observation"] = deepcopy(observation)
        trace.append(record)
        tool_message = {"role": "tool", "content": deepcopy(observation)}
        if action.get("call_id"):
            tool_message["tool_call_id"] = action["call_id"]
        messages.append(tool_message)
    return {"answer": "已达到最大执行步数，尚未得到最终回答。", "trace": trace, "messages": messages, "error": "max_steps_exceeded"}
