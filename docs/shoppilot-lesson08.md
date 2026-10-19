# ShopPilot 第八课：FastAPI Agent 服务集成

## 模块职责

| 模块 | 输入 | 输出 | 职责 |
|---|---|---|---|
| `agent-service/app.py` | HTTP JSON `{"message":"..."}` | `answer/status/trace/request_id` | 参数校验、模式选择、依赖注入、错误映射和脱敏 |
| `examples/react_agent.py` | 用户问题、LLM、工具映射 | 回答、Trace、内部消息、错误码 | 多轮 Action → Observation → Final 执行循环 |
| `examples/real_llm.py` | 内部消息 | `tool_call` 或 `final` | 将消息转成 OpenAI-compatible Tool Calling 协议 |
| `examples/product_api_tools.py` | 关键词或商品 ID | 标准化商品数据 | 通过 Go HTTP API 只读查询商品 |
| `examples/react_agent.py` 的 `FakeLLM` 和内存工具 | 固定测试商品 | 模拟动作及商品 | 离线演示，无网络和 API Key |

`GET /health` 仅检查 Python 进程并返回当前模式，不代表 Go API、MySQL 或 LLM 已连接。`POST /api/agent/chat` 中 `message` 必须是非空字符串，最多 2000 字。成功响应示例：

```json
{"answer":"轻便运动鞋：199 元，类别是运动鞋。","status":"ok","trace":[{"step":1,"model_input":[{"role":"user","content":"推荐运动鞋并查看第一款详情"}],"model_output":{"type":"tool_call","tool":"search_products","arguments":{"keyword":"运动鞋","max_price":null}},"observation":{"tool":"search_products","status":"ok","result":[{"id":"p1","name":"轻便运动鞋","price":199}],"message":"执行成功"}}],"request_id":"独立的请求标识"}
```

上例只展示第一轮 Trace 结构。实际响应还包含查询详情和 Final 的后续记录。Trace 中的 `model_input` 是该轮决策时的完整上下文；`model_output` 是 Action 或 Final；`observation` 是工具返回值。最终回答由现有 `run_react()` 生成，服务层没有复制 Agent 循环。

## 一次完整调用链

以 real 模式输入“推荐 Mouse 并查看第一款详情”为例：

1. FastAPI 校验 `message`，生成 `request_id`。
2. `RealLLM.decide(messages)` 调用配置的模型，模型选择 `search_products` 和参数 `{"keyword":"Mouse"}`。
3. `run_react()` 将 Action 记入 Trace，调用 `ProductAPITools.search_products()`。
4. 商品工具请求 Go 的 `GET /api/v1/products?keyword=Mouse&page=1&page_size=100`；Go Store 读取 MySQL，返回商品分页；Python 检查分页与 `total` 一致并标准化字段。
5. 搜索 Observation 连同原生 `tool_call_id` 回填 `messages`。模型再次决策，选择 `get_product_detail`，参数为上一轮返回的商品 ID。
6. 工具请求 `GET /api/v1/products/p_mouse_001`，详情 Observation 再次回填。模型输出 Final。HTTP 响应包含完整 Trace。

这里的 `Quiet Mouse S`、价格 129.00、库存 120 是先前已验证过的实际数据；本课默认测试使用 Mock 数据，不能据此声称本轮再次连通了 MySQL。离线模式使用第一课固定商品，商品 ID 为 `p1` 等。

## 模式与配置

默认 `SHOP_AGENT_MODE=offline`。此时使用 `FakeLLM` 与内存商品，测试和启动都不访问网络。`SHOP_AGENT_MODE=real` 时使用 `RealLLM`、`ProductAPITools`；需设置 `OPENAI_API_KEY`、`OPENAI_MODEL`、可选 `OPENAI_BASE_URL`，以及 `SHOP_API_BASE_URL`。服务延迟创建真实客户端，因此健康检查不会触发模型或商品接口调用。

## 错误与安全

| 情况 | HTTP | `status` |
|---|---:|---|
| 参数无效或空白 | 422 | `invalid_request` |
| 缺少 real 模式配置 | 503 | `configuration_error` |
| 模型调用失败 | 502 | `model_error` |
| 模型动作非法 | 502 | `invalid_action` |
| 工具执行失败 | 502 | `tool_error` |
| 超过最大迭代次数 | 504 | `max_steps_exceeded` |
| 业务上无匹配商品 | 200 | `ok`，Trace 的 Observation 为 `empty` |

工具失败会先进入 Observation，供模型决定如何解释或重试。当前 HTTP 状态只要 Trace 中存在执行失败便返回 `tool_error`；这能避免把一次失败查询包装成商品查询成功。环境中的 API Key、数据库密码和 DSN，以及常见 Bearer/密码格式会在 HTTP 回答及 Trace 中脱敏。生产环境仍应限制 Trace 接口访问权限，因为用户输入和商品数据也会出现在 Trace 中。

## PowerShell 运行与测试

在仓库根目录执行：

```powershell
python -m pip install -r agent-service/requirements.txt
$env:SHOP_AGENT_MODE = "offline"
python -m uvicorn app:app --app-dir agent-service --host 127.0.0.1 --port 8001
```

另一 PowerShell 窗口：

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/api/agent/chat -Method Post -ContentType "application/json" -Body '{"message":"推荐运动鞋并查看第一款详情"}'
python -m pytest agent-service/examples agent-service/evals agent-service/test_app.py -q
```

真实模式需先启动 Go API 和 MySQL，再设置 `SHOP_AGENT_MODE=real`、`SHOP_API_BASE_URL=http://127.0.0.1:8080` 和模型配置，重启 uvicorn。独立的只读 Go API 验证脚本需显式执行，默认 pytest 不会运行：

```powershell
python agent-service/scripts/verify_go_products.py --base-url http://127.0.0.1:8080
```

该脚本搜索 Mouse 并查询 `p_mouse_001` 详情；若分页 `total` 与 items 不一致，商品工具会明确报错。
