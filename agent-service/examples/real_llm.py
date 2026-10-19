"""OpenAI-compatible Chat Completions 的原生 Tool Calling 适配层。"""

import json
import os


TOOLS = [
    {"type": "function", "function": {"name": "search_products", "description": "按商品关键词和可选最高价格搜索商品", "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "商品名称或类别关键词"}, "max_price": {"type": ["integer", "null"], "description": "最高价格，正整数；没有预算时为 null"}}, "required": ["keyword"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_product_detail", "description": "根据搜索结果中的商品 ID 查询详情", "parameters": {"type": "object", "properties": {"product_id": {"type": "string", "description": "商品 ID，如 p1"}}, "required": ["product_id"], "additionalProperties": False}}},
]


class ModelCallError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RealLLM:
    """对外返回与 FakeLLM 相同的 tool_call/final 动作。"""

    def __init__(self, client=None, api_key=None, base_url=None, model=None):
        self.model = model or os.getenv("OPENAI_MODEL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if not self.api_key:
            raise ModelCallError("missing_api_key")
        if not self.model:
            raise ModelCallError("missing_model")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ModelCallError("missing_openai_sdk") from exc
            options = {"api_key": self.api_key, "timeout": 30.0, "max_retries": 0}
            if self.base_url:
                options["base_url"] = self.base_url
            client = OpenAI(**options)
        self.client = client

    @staticmethod
    def _api_messages(messages):
        output = [{"role": "system", "content": "你是商品导购。需要商品信息时调用工具；每次只调用一个工具。根据工具结果回答，不编造商品。"}]
        for message in messages:
            role, content = message["role"], message["content"]
            if role == "user":
                output.append({"role": "user", "content": content})
            elif role == "assistant" and content["type"] == "tool_call":
                call_id = content.get("call_id")
                if not call_id:
                    raise ModelCallError("missing_tool_call_id")
                output.append({"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": content["tool"], "arguments": json.dumps(content["arguments"], ensure_ascii=False)}}]})
            elif role == "assistant" and content["type"] == "final":
                output.append({"role": "assistant", "content": content["text"]})
            elif role == "tool":
                if not message.get("tool_call_id"):
                    raise ModelCallError("missing_tool_call_id")
                output.append({"role": "tool", "tool_call_id": message["tool_call_id"], "content": json.dumps(content, ensure_ascii=False)})
            else:
                raise ModelCallError("invalid_message")
        return output

    def decide(self, messages):
        api_messages = self._api_messages(messages)
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=api_messages, tools=TOOLS,
                tool_choice="auto", parallel_tool_calls=False,
            )
        except Exception as exc:
            name = type(exc).__name__
            code = {"APITimeoutError": "model_timeout", "APIConnectionError": "model_connection_error", "RateLimitError": "model_rate_limited"}.get(name, "model_api_error")
            raise ModelCallError(code) from exc
        try:
            message = response.choices[0].message
            calls = message.tool_calls or []
            if len(calls) > 1:
                raise ModelCallError("multiple_tool_calls")
            if calls:
                call = calls[0]
                if not isinstance(call.id, str) or not call.id or call.type != "function":
                    raise ModelCallError("invalid_model_response")
                arguments = json.loads(call.function.arguments)
                if not isinstance(arguments, dict):
                    raise ModelCallError("invalid_model_response")
                return {"type": "tool_call", "tool": call.function.name, "arguments": arguments, "call_id": call.id}
            if not isinstance(message.content, str) or not message.content.strip():
                raise ModelCallError("invalid_model_response")
            return {"type": "final", "text": message.content}
        except (AttributeError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelCallError("invalid_model_response") from exc
