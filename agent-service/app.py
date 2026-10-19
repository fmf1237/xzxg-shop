"""ShopPilot 第八课：把既有 ReAct 循环暴露为 HTTP 服务。"""

import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent / "examples"))
from product_api_tools import ProductAPITools  # noqa: E402
from react_agent import FakeLLM, get_product_detail, run_react, search_products  # noqa: E402
from real_llm import RealLLM  # noqa: E402


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _clean(value):
    """Trace 供调试使用，但不能把进程配置中的密钥带入响应。"""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if not isinstance(value, str):
        return value
    for name in ("OPENAI_API_KEY", "MYSQL_PASSWORD", "DB_PASSWORD", "MYSQL_DSN", "DATABASE_URL"):
        secret = os.getenv(name)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)\b(bearer\s+)[^\s,;]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)\b((?:api[_-]?key|password)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    return value


def _reply(answer, status, trace, request_id, http_status=200):
    return JSONResponse(
        status_code=http_status,
        content={"answer": _clean(answer), "status": status, "trace": _clean(trace), "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


def create_app(mode=None, llm=None, product_tools=None, max_steps=5):
    """依赖可注入；默认 offline 不创建网络客户端。"""
    selected_mode = (mode or os.getenv("SHOP_AGENT_MODE", "offline")).lower()
    if selected_mode not in ("offline", "real"):
        raise ValueError("SHOP_AGENT_MODE 必须是 offline 或 real")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps 必须是正整数")
    service = FastAPI(title="ShopPilot Agent", version="0.1.0")
    dependencies = {}

    def get_dependencies():
        if "llm" not in dependencies:
            dependencies["llm"] = llm if llm is not None else (FakeLLM() if selected_mode == "offline" else RealLLM())
        if "tools" not in dependencies:
            if product_tools is not None:
                source = product_tools
                dependencies["tools"] = {"search_products": source.search_products, "get_product_detail": source.get_product_detail}
            elif selected_mode == "offline":
                dependencies["tools"] = {"search_products": search_products, "get_product_detail": get_product_detail}
            else:
                source = ProductAPITools()
                dependencies["tools"] = {"search_products": source.search_products, "get_product_detail": source.get_product_detail}
        return dependencies["llm"], dependencies["tools"]

    @service.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _reply("请求参数错误：message 必须是 1–2000 字的字符串。", "invalid_request", [], uuid4().hex, 422)

    @service.get("/health")
    def health():
        return {"status": "ok", "mode": selected_mode}

    @service.post("/api/agent/chat")
    def chat(payload: ChatRequest):
        request_id = uuid4().hex
        if not payload.message.strip():
            return _reply("请求参数错误：message 不能为空。", "invalid_request", [], request_id, 422)
        try:
            active_llm, tools = get_dependencies()
        except Exception as exc:
            code = getattr(exc, "code", "configuration_error")
            return _reply(f"服务配置错误：{code}", "configuration_error", [], request_id, 503)
        result = run_react(payload.message, llm=active_llm, max_steps=max_steps, tools=tools)
        trace = result["trace"]
        error = result["error"]
        if error == "max_steps_exceeded":
            return _reply(result["answer"], error, trace, request_id, 504)
        if error:
            if error.startswith("model_") or error in ("invalid_model_response", "multiple_tool_calls", "missing_tool_call_id"):
                status = "model_error"
            else:
                status = "invalid_action"
            return _reply(result["answer"], status, trace, request_id, 502)
        # FakeLLM 可能在失败 Observation 后输出 final；不能把它当作查询成功。
        failed = [record["observation"] for record in trace if record.get("observation", {}).get("status") == "error"]
        if failed:
            return _reply(result["answer"], "tool_error", trace, request_id, 502)
        return _reply(result["answer"], "ok", trace, request_id)

    return service


app = create_app()
