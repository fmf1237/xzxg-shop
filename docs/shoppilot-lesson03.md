# ShopPilot 第三课：真实模型 Tool Calling

## 本课做了什么

第二课 `FakeLLM.decide(messages)` 用规则选工具；本课 `RealLLM.decide(messages)` 把同一份执行上下文转换为 OpenAI-compatible Chat Completions 消息，交给模型自主选择工具。两者都返回 `{"type": "tool_call", ...}` 或 `{"type": "final", ...}`，所以继续复用 `run_react()` 的循环、工具分发、Observation 和 Trace。

OpenAI-compatible API 指其他供应商提供与 OpenAI Chat Completions 相近的请求和响应协议。通过 `OPENAI_BASE_URL` 可以切换服务地址；`OPENAI_API_KEY` 提供密钥，`OPENAI_MODEL` 指定模型。兼容程度因供应商而异，本例要求其支持原生 `tools`、`tool_calls`、`tool_call_id` 和 `parallel_tool_calls` 参数。

## Tool Schema 和真实消息流

[`real_llm.py`](../agent-service/examples/real_llm.py) 的 `TOOLS` 为 `search_products` 和 `get_product_detail` 定义名称、用途、参数类型和必填字段。模型在每次请求的 `tools` 字段中看到这些 Schema，才知道有哪些工具以及怎样传参。Schema 是给模型的约束说明，Python 工具本身仍会检查参数；例如 `product_id` 若为数字，工具返回参数错误 Observation。

一次搜索的 API 消息序列大致如下：

```json
[
  {"role": "user", "content": "推荐运动鞋并查看第一款详情"},
  {"role": "assistant", "content": null, "tool_calls": [{"id": "call_search", "type": "function", "function": {"name": "search_products", "arguments": "{\"keyword\": \"运动鞋\"}"}}]},
  {"role": "tool", "tool_call_id": "call_search", "content": "{\"tool\": \"search_products\", \"status\": \"ok\", \"result\": [...]}"}
]
```

模型先返回原生 Tool Call，其中 `function.arguments` 是 JSON 字符串。`RealLLM.decide()` 将其解析成内部 Action，并保留 `call_id`。`run_react()` 执行 Python 工具后，将 Observation 与同一个 ID 写入 `messages`。下一轮适配器还原为 `assistant.tool_calls` 和 `tool.tool_call_id`；ID 让模型知道哪条工具结果对应哪次调用。第二次调用 `get_product_detail` 后重复这个过程，直到模型给出 Final。

本课每轮只允许一个工具调用，请求设置 `parallel_tool_calls=False`。若供应商仍返回多个调用，代码明确报 `multiple_tool_calls`，不会遗漏结果或产生无效的消息历史。

## 输入、输出与错误

| 步骤 | 输入 | 输出 |
| --- | --- | --- |
| `RealLLM._api_messages()` | `run_react()` 的内部 `messages` | 含 system、user、assistant tool_calls 和 tool result 的 API 消息 |
| `RealLLM.decide()` | 完整内部上下文 | 统一的 `tool_call` 或 `final` Action |
| `_execute()` | 工具名与参数 | `ok`、`empty` 或 `error` Observation |
| `run_react()` | 用户问题、RealLLM | 最终回答、逐轮 Trace、消息列表、错误码 |

模型超时、连接失败、限流和非法响应分别产生 `model_timeout`、`model_connection_error`、`model_rate_limited`、`invalid_model_response` 等模型错误码，循环安全停止。未知工具、参数错误、工具执行异常属于工具错误，会作为 Observation 送回模型；搜索不到商品属于 `empty`，不等同异常。达到步数限制会返回 `max_steps_exceeded`。

## 运行方法

仅运行离线测试，不需要密钥：

```bash
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py agent-service/examples/test_real_llm.py -q
```

若要主动测试真实服务，先在本机环境中配置 `OPENAI_API_KEY`、`OPENAI_MODEL`，第三方供应商还需配置 `OPENAI_BASE_URL`，并安装 `openai` Python SDK。然后在仓库根目录运行：

```bash
python agent-service/examples/run_real_agent.py "推荐运动鞋并查看第一款详情"
```

命令行程序输出每轮动作、Observation、最终回答、调用次数与耗时，不打印密钥。测试使用 Mock 客户端；未配置凭据时不执行真实调用，也不推测模型的真实回答。

## 对照 Go 项目

`backend/src/agent/llm.go` 的 `LLMClient` 管理模型地址、密钥和 HTTP 请求；本课的 `RealLLM` 承担类似的适配职责。`backend/src/agent/react.go` 的 `runReactAgent` 对应 Python `run_react()` 的多轮循环。`backend/src/agent/tools.go` 的 `reactAction`、`toolObservation`、`executeTool` 分别对应内部 Action、Observation 和 `_execute()`。Go 项目还有意图规划、工具策略、流式输出和复杂业务工具，本例仅保留两种内存商品工具。

## 五道面试题

1. **FakeLLM 与 RealLLM 的共同接口是什么？** 都接收 `messages`，返回统一的工具 Action 或 Final，执行循环无需关心决策来源。
2. **为什么 Tool Schema 重要？** 它告知模型工具用途与参数形状，减少错误调用；应用端仍须再次校验。
3. **Tool Call ID 的用途是什么？** 将工具结果与对应模型调用关联，维持多轮消息协议的完整性。
4. **模型调用失败与工具调用失败如何区分？** 前者没有可靠模型动作，应停止并报告模型错误；后者可以作为 Observation 回填，让模型继续决策。
5. **模型一次返回多个工具调用怎么办？** 执行器必须完整处理或明确拒绝；本课选择明确拒绝，避免静默丢弃。
