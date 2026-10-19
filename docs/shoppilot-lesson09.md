# ShopPilot 第九课：真实集成验证与稳定性

## 当前请求链

```text
POST /api/agent/chat {message}
  → app.py 校验、生成 request_id、选择 offline/real 依赖
  → run_react(message, llm, tools) 新建 messages 与 trace
  → FakeLLM 或 RealLLM 决定 Action
  → search_products → Go GET /api/v1/products → Store → MySQL
  → Observation 写入本请求 messages
  → get_product_detail → Go GET /api/v1/products/{id} → Store → MySQL
  → Observation 写入本请求 messages
  → LLM 决定 Final → FastAPI 返回 answer/status/trace/request_id
```

输入是 JSON 对象，`message` 为非空字符串。输出字段为 `answer`、`status`、`trace` 和 `request_id`；`X-Request-ID` 响应头与响应体一致。Trace 每轮含模型输入和输出；工具轮另含 Observation。真实商品工具使用现有 `ProductAPITools`，不直接连接数据库。

## 并发隔离

`run_react()` 每次调用都在函数内创建新的 `messages` 和 `trace`，调用模型时还复制消息。服务复用无会话历史的 `FakeLLM` 或 `RealLLM` 客户端及工具配置，不在全局对象中保存用户对话。第九课给 LLM 的首次延迟初始化加锁，避免并发请求重复创建客户端。真实商品工具的 `requests.Session` 按工作线程创建并复用，避免多线程同时操作同一个 Session。`request_id` 每次请求单独生成。

离线并发测试同时发送 20 个不同问题，逐条检查回答、首轮模型输入、后续 Observation 和唯一 request_id，确认本请求的 Trace 不包含其他请求的数据。这里验证的是线程并发；多进程部署仍由各进程分别持有自己的客户端。

## 异常传播与安全

商品 API 的超时、HTTP 500 和非法 JSON 会由 `ProductAPITools` 转成带 `error_code` 的异常，再由 `run_react()` 包装为失败 Observation。模型能读到该 Observation 并选择最终解释。HTTP 层会返回 `tool_error` 和 502，而不会声称商品查询成功。未分类工具异常在公开 HTTP Trace 中仅显示“工具执行异常”；服务未预料异常返回 500 `internal_error`，不回传堆栈或异常文本。已知模型调用失败返回 `model_error`；未知模型异常转为非法动作而不公开异常文本。最大迭代次数返回 504 `max_steps_exceeded`。业务空结果仍是 `empty` Observation，与执行异常不同。

教学环境默认返回完整 Trace。它可能包含用户输入和商品数据，实际部署应在网关限制 `/api/agent/chat` 访问，或设置 `SHOP_AGENT_TRACE_ENABLED=false`，只保留回答、状态和请求标识。API Key、数据库密码和 DSN 会脱敏，但脱敏不能替代访问控制。真实 LLM 供应商仍可能看到发给它的用户消息与工具结果，应按部署要求管理这些数据。

## 验证方法与实际结果

离线测试命令：

```powershell
python -m pytest agent-service/examples agent-service/evals agent-service/test_app.py agent-service/test_lesson09.py -q
```

本地结果：79 项通过，1 条 Starlette TestClient 的弃用警告。覆盖并发隔离、工具超时、HTTP 500、非法 JSON、模型异常、服务未预料异常、最大步数及前八课回归。

显式运行真实 Go API 链路，无需真实 LLM：

```powershell
python agent-service/scripts/verify_real_tool_chain.py --base-url http://127.0.0.1:8080
```

脚本内 Mock LLM 只决定搜索 Mouse、选择搜索返回的 `p_mouse_001`、查询详情。Final 文本从详情 Observation 的 `name`、`price`、`stock_quantity` 生成，随后逐项核对回答是否包含这些实时返回字段。它不预置数据库商品名称、价格或库存。2026-10-19 本地显式运行结果为 `status=ok`，调用 2 次工具，回答引用 Go API 返回的 Quiet Mouse S、129.00 元、库存 120 件。该结果证明本机当时 Go API 与 MySQL 查询可用；没有验证真实 LLM API。默认 pytest 不运行此脚本，也不要求 Docker、Go 或网络。
