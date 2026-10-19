# ShopPilot 第十课：真实 LLM Tool Calling 端到端验证

## 本课验证的链路

固定测试问题进入 FastAPI `POST /api/agent/chat`。服务调用现有 `run_react()`，由 `RealLLM.decide(messages)` 请求 OpenAI-compatible Chat Completions。模型自主选择 `search_products`、`get_product_detail` 或直接回答；Python 执行工具，经 Go HTTP API 从 MySQL 只读获取商品。每次工具结果以 Observation 回填给模型，再进入下一轮，直到 Final 或最大步数。脚本没有复制 ReAct 循环，也没有为模型预填工具选择结果。

`real_llm.py` 发送的请求包含 `messages`、两个工具的 JSON Schema、`tool_choice="auto"`、`parallel_tool_calls=False`。返回的原生 `tool_calls[0]` 包含调用 ID、函数名和 JSON 参数。内部动作形如 `{"type":"tool_call","tool":"search_products","arguments":{"keyword":"Mouse"},"call_id":"..."}`。执行后，`react_agent.py` 将带 `tool_call_id` 的 Observation 放入下一次模型请求的 `tool` 消息。模型直接回答时转成 `{"type":"final","text":"..."}`。供应商若仍一次返回多个调用，适配器会明确报错，不会静默丢弃。

## 显式运行

先启动 Go API 和 MySQL；在 PowerShell 中设置本机模型配置。请勿将密钥写入脚本或提交到 GitHub：

```powershell
$env:OPENAI_API_KEY = "从私密配置取得的密钥"
$env:OPENAI_MODEL = "支持 Chat Completions Tool Calling 的模型名"
$env:OPENAI_BASE_URL = "供应商兼容接口地址" # 使用 OpenAI 默认地址时可不设置
$env:SHOP_API_BASE_URL = "http://127.0.0.1:8080"
python agent-service/scripts/verify_real_llm_e2e.py
```

可选 `--base-url` 指定 Go API，`--output` 写入仅供本机分析的 JSON 报告。默认不写报告文件。脚本包含四个独立请求：Mouse 第一款详情、300 元以内鼠标、明确不存在的商品、注入商品工具 HTTP 500。前三个使用真实 Go 商品 HTTP 工具；最后一个故意注入工具失败，仍使用真实模型观察它是否诚实回答。真实模型可能自主作出不同动作；脚本会将偏差记为失败，不用固定模型输出来让测试通过。

每条记录包含模型名、工具调用顺序与参数、Observation、模型原始 Final、FastAPI 回答、延迟、每次模型调用的 Token 用量（供应商返回时）以及失败原因。详情案例核对回答的名称、价格和库存是否来自详情 Observation；预算案例核对搜索参数及被推荐商品的名称和价格是否在 300 元以内；无结果与工具错误案例检查模型是否明确说明无法提供商品结果。自动检查只是基本约束，仍需人工阅读原始 Final，判断措辞和事实是否完整。

## 错误与局限

模型可能直接回答而不调用工具、把中文“鼠标”错误翻译成不匹配的关键词、参数不符合 Schema、漏查详情、忽略空 Observation、把工具失败说成成功，或在最大步数内无法结束。这些均应在报告中保留。`ProductAPITools` 会区分业务空结果和超时、HTTP 状态、JSON 格式错误。FastAPI 为工具失败返回 `tool_error`；验证脚本另外读取本次运行捕获的模型原始 Final，以免 HTTP 的安全兜底回答掩盖模型自身的错误。供应商未返回 `usage` 时 Token 字段为 `null`，不能推断为零。

当前环境（2026-10-19）未配置 `OPENAI_API_KEY`、`OPENAI_MODEL` 和 `OPENAI_BASE_URL`。因此**真实模型端到端验证尚未运行，四个真实模型案例没有成功或失败结论**。此前第九课用 Mock LLM 连通 Go API 和 MySQL 的结果不能代替本课的模型验证。默认 pytest 只运行离线测试，包括验证脚本的判定逻辑，不访问模型或 Go API。

本地离线测试结果：**82 passed，1 条 Starlette TestClient 弃用警告**。显式执行验证脚本时，因缺少模型配置而在发出任何模型或商品请求前退出；没有生成真实模型报告。

```powershell
python -m pytest agent-service/examples agent-service/evals agent-service/test_app.py agent-service/test_lesson09.py agent-service/test_lesson10.py -q
```
