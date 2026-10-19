"""第一课：只用规则和内存商品实现最小 Agent。"""

import re


PRODUCTS = [
    {"id": "p1", "name": "轻便运动鞋", "category": "运动鞋", "price": 199},
    {"id": "p2", "name": "缓震运动鞋", "category": "运动鞋", "price": 399},
    {"id": "p3", "name": "保湿面霜", "category": "面霜", "price": 259},
    {"id": "p4", "name": "机械键盘", "category": "键盘", "price": 299},
]


def plan(user_input):
    """输入用户文字，输出 action、keyword、max_price 组成的计划。"""
    if not isinstance(user_input, str) or not user_input.strip():
        raise ValueError("用户输入不能为空")
    query = user_input.strip()
    budget_match = re.search(r"(?:预算|不超过|低于|以内|以下)\s*(\S+?)\s*元", query)
    max_price = None
    if budget_match:
        value = budget_match.group(1)
        if not value.isdigit() or int(value) <= 0:
            raise ValueError("预算必须是大于 0 的整数")
        max_price = int(value)

    keyword = next(
        (word for word in ("运动鞋", "面霜", "键盘") if word in query), None
    )
    shopping = keyword is not None or any(
        word in query for word in ("推荐", "买", "商品", "找一", "找个")
    )
    if shopping:
        # 没识别到商品名时，保留原句作为检索词，工具会返回空结果。
        return {"action": "search_products", "keyword": keyword or query, "max_price": max_price}
    return {"action": "chat", "keyword": None, "max_price": None}


def search_products(keyword, max_price=None):
    """输入关键词和可选最高价，输出匹配商品列表。"""
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("商品关键词不能为空")
    if max_price is not None and (
        isinstance(max_price, bool) or not isinstance(max_price, int) or max_price <= 0
    ):
        raise ValueError("预算必须是大于 0 的整数")
    term = keyword.strip()
    return [
        product.copy()
        for product in PRODUCTS
        if (term in product["name"] or term in product["category"])
        and (max_price is None or product["price"] <= max_price)
    ]


def run_agent(user_input):
    """执行一次规划、工具调用和回答，并返回每一步的输入输出。"""
    steps = []
    try:
        execution_plan = plan(user_input)
        steps.append({"stage": "plan", "input": user_input, "output": execution_plan})
        action = execution_plan["action"]
        if action == "chat":
            answer = "你好！你可以告诉我想找什么商品和预算。"
        elif action == "search_products":
            arguments = {
                "keyword": execution_plan["keyword"],
                "max_price": execution_plan["max_price"],
            }
            try:
                products = search_products(**arguments)
            except Exception as exc:
                steps.append({"stage": "tool", "input": arguments, "error": str(exc)})
                raise RuntimeError("商品搜索工具执行失败") from exc
            steps.append({"stage": "tool", "input": arguments, "output": products})
            answer = (
                "找到商品：" + "；".join(f'{item["name"]}（{item["price"]} 元）' for item in products)
                if products else "没有找到符合要求的商品，请换个关键词或提高预算。"
            )
        else:
            raise ValueError(f"Planner 返回未知动作：{action}")
        steps.append({"stage": "answer", "input": steps[-1]["output"], "output": answer})
        return {"answer": answer, "steps": steps, "error": None}
    except (ValueError, RuntimeError) as exc:
        steps.append({"stage": "error", "input": user_input, "output": str(exc)})
        return {"answer": str(exc), "steps": steps, "error": str(exc)}
