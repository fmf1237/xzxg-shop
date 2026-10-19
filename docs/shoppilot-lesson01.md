# ShopPilot 第一课：最小 Python Agent

## 三个角色

- **Agent** 是总负责人：接收问题，安排步骤，拿到结果后回答用户。本课由 `run_agent()` 承担。
- **Planner** 决定下一步做什么。本课 `plan()` 用简单规则判断“商品推荐”或“普通聊天”，并提取关键词、预算。
- **Tool** 执行具体操作。本课 `search_products()` 在内存商品列表里搜索。

分开后，每一层只做一件事：可以单独检查规划是否正确、搜索是否正确、回答是否正确。以后替换规划规则或商品来源时，也容易找到改动位置。

## 函数输入和输出

| 函数 | 输入 | 输出 |
| --- | --- | --- |
| `plan(user_input)` | 用户文字，如 `推荐运动鞋，预算 200 元` | 字典，如 `{"action": "search_products", "keyword": "运动鞋", "max_price": 200}`；非法输入抛 `ValueError` |
| `search_products(keyword, max_price)` | 商品关键词、可选的最高整数价格 | 商品字典列表；找不到时返回 `[]`；非法参数抛 `ValueError` |
| `run_agent(user_input)` | 用户文字 | 包含 `answer`、`steps`、`error` 的字典；把可预期异常转为可观察结果 |

本课只识别示例商品类别“运动鞋、面霜、键盘”。规则没有理解语言的能力；其他推荐请求会进入搜索，但可能得到空结果。

## 一次执行流程

输入：`推荐运动鞋，预算 200 元`

1. `plan()` 输出 `{"action": "search_products", "keyword": "运动鞋", "max_price": 200}`。
2. `run_agent()` 按 `action` 选择 `search_products()`，传入关键词和预算。
3. 工具检查内存商品，只留下价格 199 元的“轻便运动鞋”。
4. `run_agent()` 生成回答：`找到商品：轻便运动鞋（199 元）`。
5. 返回的 `steps` 依次记录 `plan`、`tool`、`answer` 的输入和输出。

## 关键 Python 代码

源码在 [`agent-service/examples/minimal_agent.py`](../agent-service/examples/minimal_agent.py)。

```python
execution_plan = plan(user_input)
action = execution_plan["action"]
if action == "search_products":
    products = search_products(
        execution_plan["keyword"], execution_plan["max_price"]
    )
```

第一行生成结构化计划；`action` 是分支开关；只有需要商品推荐时才调用搜索工具。`search_products()` 用列表推导式同时检查关键词和最高价。`run_agent()` 把每步记录到 `steps`，便于看到问题发生在哪一层。搜索不到商品时返回空列表，由 Agent 生成提示。预算非法、未知动作和工具异常会进入错误记录。

## 与原 Go 项目的对应关系

| 本课 | Go 源码位置 | 对应职责 |
| --- | --- | --- |
| `run_agent()` | `backend/src/agent/runtime.go` 的 `Runtime.Stream`（第 56 行） | 单轮入口，规划后执行并输出结果 |
| `plan()` | `backend/src/agent/runtime.go` 的 `Runtime.plan`（第 347 行）和 `classifyIntent`（第 354 行） | 判断路由和意图 |
| 工具调度 | `backend/src/agent/react.go` 的 `runReactAgent`（第 32 行） | 根据动作循环调用工具、处理 Observation |
| `search_products()` | `backend/src/agent/tools.go` 的 `executeTool`（第 184 行）和 `toolSearchProducts`（第 422 行） | 派发工具并搜索商品 |
| HTTP 入口 | `backend/src/httpapi/server.go` 的 `streamAgentRun`（第 2366 行） | 将 Agent 运行结果通过 SSE 发给客户端 |

Go 项目还有风控、对话上下文、动态配置、模型调用和链路追踪；本课没有实现这些功能。

## 与真正 ReAct Agent 的区别

本课的规则 Planner 只规划一次，最多调用一次搜索工具，然后拼接回答。真正的 ReAct 会反复进行“决定动作 → 执行工具 → 观察结果 → 再决定”，直到得到最终答案或达到步数上限。原项目的 `runReactAgent` 使用模型产生动作，执行工具后把 Observation 放回下一轮上下文；本课没有调用模型，也没有多轮决策。

## 运行测试

在仓库根目录执行：

```bash
python -m pytest agent-service/examples/test_minimal_agent.py -q
```

测试覆盖正常推荐、预算、无匹配商品、聊天、非法输入或预算、未知动作和工具异常。

## 五道基础面试题

1. **Agent、Planner、Tool 各做什么？** Agent 组织整个流程；Planner 决定下一步；Tool 执行具体操作。
2. **为什么 Planner 不直接搜索商品？** 把决策和操作分开，才能分别测试和更换实现。
3. **Tool 返回空列表一定是异常吗？** 不是。它表示搜索成功，但没有匹配商品；Agent 应给用户明确提示。
4. **为什么需要执行记录？** 可以看到计划、工具参数和结果，快速定位错误，也便于以后做调试和评估。
5. **这个示例为什么还不是真正的 ReAct？** 它没有模型驱动的多轮“动作与观察”循环，只做一次规则规划和一次工具调用。
