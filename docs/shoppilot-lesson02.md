# ShopPilot 第二课：最小多轮 ReAct Agent

## 从第一课到 ReAct

第一课的 `plan()` 只决策一次：选搜索或聊天，然后直接回答。第二课的 `run_react()` 会循环：模型给出 **Action**，程序调用工具得到 **Observation**，模型看过结果后继续选择工具或输出 **Final**。这里的模型是规则类 `FakeLLM`，没有真实 API；它每轮读取传入的 `messages`，不依赖调用次数。

Action 是 `{"type": "tool_call", "tool": "search_products", "arguments": {...}}` 这样的工具请求。Observation 是工具的结构化反馈，含工具名、`status`、`result`、`message`。`status="empty"` 表示执行成功但无业务结果，`status="error"` 表示工具名、参数或执行出了问题。Final 是 `{"type": "final", "text": "..."}`，结束循环。

## messages 与每轮输入输出

`messages` 开始只有一条用户问题。每次工具调用后，程序依次追加 assistant 的 Action 和 tool 的 Observation。下一轮把完整 `messages` 交给 FakeLLM，因此它可以根据刚才搜到的商品 ID 决定是否查询详情，也能在工具失败后解释错误。`trace` 中的 `model_input` 是该轮输入上下文的快照，`model_output` 是模型动作；工具轮还有 `observation`。快照让后续消息变化不影响历史记录。

## 两次工具调用案例

输入：`推荐运动鞋并查看第一款详情`

| 轮次 | 模型看到的关键信息 | 模型输出 | 工具反馈 |
| --- | --- | --- | --- |
| 1 | 用户问题 | `search_products(keyword="运动鞋")` | 返回 `p1` 轻便运动鞋和 `p2` 缓震运动鞋 |
| 2 | 用户问题、搜索 Action、搜索 Observation | `get_product_detail(product_id="p1")` | 返回 `p1` 的完整商品数据 |
| 3 | 前两轮所有 Action 和 Observation | Final：`轻便运动鞋：199 元，类别是运动鞋。` | 无工具调用 |

两个工具分别在 [`react_agent.py`](../agent-service/examples/react_agent.py) 中实现。商品数据复用第一课的内存列表，不访问 MySQL。`run_react()` 中的 `for step in range(1, max_steps + 1)` 控制最大轮数，避免模型反复请求工具导致无限执行与资源消耗。达到上限时返回 `max_steps_exceeded` 和已有 Trace。

工具错误应反馈给模型，因为模型需要知道操作失败，才能解释原因或尝试其他行动。本例 FakeLLM 收到 `error` 后给出 Final；真正模型也可能决定换工具或修改参数。非法模型动作无法可靠派发，程序直接返回 `invalid_action`。未知工具和参数错误会包装为 `error` Observation；搜索为空包装为 `empty` Observation，两者不会混淆。

## 对照 Go 源码

| Python 示例 | Go 源码 | 作用 |
| --- | --- | --- |
| `run_react()` | `backend/src/agent/react.go` 的 `runReactAgent`（第 32 行） | 多轮决策循环 |
| `FakeLLM.decide()` | `backend/src/agent/react.go` 的 `streamReactStep`（第 266 行） | 生成下一步动作或最终回答 |
| Action 字典 | `backend/src/agent/tools.go` 的 `reactAction`（第 49 行） | 表示工具调用或 Final |
| Observation 字典 | `backend/src/agent/tools.go` 的 `toolObservation`（第 64 行） | 保存工具执行反馈 |
| `_execute()` | `backend/src/agent/tools.go` 的 `executeTool`（第 184 行） | 按工具名称派发执行 |
| 上层入口 | `backend/src/agent/runtime.go` 的 `Runtime.Stream`（第 56 行） | 先规划，再进入 ReAct，并输出结果 |

Go 代码通过 `parseReactAction` 解析模型输出，把 Action 和 Observation 回填模型上下文，再次调用模型。它还处理工具策略、trace、结构化内容、SSE 输出和模型故障兜底。Python 示例只保留教学必需的两种工具、两种动作和执行记录。

## 运行测试

在仓库根目录执行：

```bash
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py -q
```

## 五道面试题

1. **ReAct 的基本循环是什么？** 决定动作、执行工具、观察结果、再次决定，直到最终回答或达到上限。
2. **为什么要把 Observation 放回上下文？** 下一轮模型必须看到工具结果，才能选择后续动作，避免猜测商品 ID 或结果。
3. **空结果和工具异常有什么不同？** 空结果表示工具正常运行但业务数据不匹配；异常表示执行失败，应分别处理。
4. **如何防止无限工具调用？** 设置最大步数，并在达到上限时停止、记录错误和已有执行轨迹。
5. **为什么需要校验模型动作？** 模型可能输出错误类型、缺失工具名或无效参数；校验可以避免错误调用并留下明确诊断。
