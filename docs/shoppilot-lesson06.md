# ShopPilot 第六课：理解查询，再执行检索

## Query Understanding 是什么

用户说“迅步运动鞋预算300元”时，检索器不能只把整句当关键词。**Query Understanding** 把文本拆成商品类别、品牌、预算、软需求以及诊断。`parse_query()` 的输入是原始文字和目录元数据，输出是结构化字典；它只从商品目录中确认品牌与类别，不凭空猜品牌。

**Query Rewrite** 通常把问题改写成另一个检索表达式，例如把“跑鞋”扩为“运动鞋”。**Query Parser** 则把表达式拆成字段和约束。本课两者都有少量规则：受控词表归一化“跑鞋/球鞋”，Parser 输出 `category="运动鞋"`，再交给检索器。

硬约束是用户明确要求、结果必须满足的条件：目录中确认的品牌、明确类别、数字预算。软需求如“轻便”“通勤”“便宜”用于匹配和排序；“便宜”没有数值，不应擅自变成“200 元以内”。不确定的“鞋”只作为弱线索，不能强行筛掉非运动鞋。两个品牌或冲突预算会产生诊断并停止检索。

## 模块与执行过程

| 模块 | 输入 | 输出 |
| --- | --- | --- |
| [`query_parser.py`](../agent-service/evals/query_parser.py) | 原始 Query、商品目录中的品牌/类别/卖点 | `keyword`、`category`、`brand`、`max_price`、`soft_requirements`、`diagnostics` |
| [`improved_retrieval.py`](../agent-service/evals/improved_retrieval.py) | 合成商品、解析结果、K | 商品 ID 列表和包含候选、过滤原因、软匹配分数的 Trace |
| [`run_retrieval_comparison.py`](../agent-service/evals/run_retrieval_comparison.py) | 第五课商品/Query、冻结基线报告 | 总体及逐条指标、回退列表、[JSON](../agent-service/evals/reports/retrieval_comparison.json)和[Markdown](../agent-service/evals/reports/retrieval_comparison.md)报告 |

以“迅步运动鞋预算300元”为例，Parser 输出 `category=运动鞋`、`brand=迅步`、`max_price=300`。检索器先收集候选，再过滤：`s02` 399 元被标为 `over_budget`，`s03` 被标为 `brand_mismatch`，其他类别也被过滤；仅 `s01` 进入最终 Top-3。Trace 记录了每件被过滤商品的理由。过滤必须在 Top-K 之前，否则 Top-K 可能先被不符合品牌或预算的商品占满。

同义词扩展让“跑鞋”找到运动鞋，也可能让并非跑步用途的运动鞋混入。因此本课同时把“跑步/竞速”作为软需求做确定性排序；若有软匹配候选，只展示这些候选。该门槛可能误删未写明卖点的相关商品，需在更大数据集上验证。这里没有使用 Embedding、Rerank 或模型。

## 公平对比与实际结果

比较脚本读取第五课的原始 `query`，新方案推理时**不读取** `expected_product_ids` 或 `constraints`。检索完成后，才用原标签评分。商品、30 条 Query、K=3 和 [`retrieval_metrics.py`](../agent-service/evals/retrieval_metrics.py) 公式均保持不变；第五课原基线报告没有覆盖。基线使用人工抽取的 `constraints.keyword`，新方案使用原句，因此两者输入难度并不完全相同，报告应作为教学实验而非线上 A/B 结论。所有商品都是合成数据。

| 指标 | 第五课基线 | 第六课 |
| --- | ---: | ---: |
| Precision@3 | 0.3086 | 0.5062 |
| Recall@3 | 0.6173 | 0.9815 |
| Hit@3 | 0.6667 | 1.0000 |
| MRR | 0.6420 | 1.0000 |
| NDCG@3 | 0.6323 | 1.0000 |
| 明确硬约束满足率 | 0.8333 | 1.0000 |
| 按第五课标注约束的满足率 | 0.7222 | 0.9444 |
| Top-3 误召回件数 | 5 | 1 |
| 无匹配正确拒答率 | 1.0000 | 1.0000 |

没有样本发生 Recall@3 回退。重点样本：c13 从空结果到 `s01,s03`；c17 从空结果到 `s02,s06`；c21 从 `s01,s02,s03` 改为迅步商品 `s01,s02,s06`；c22 改为飞跃 `s03,s04`；c24 的 Recall 未变，但原先混入的非迅步商品被过滤，仅剩 `s01`。

**剩余问题与标签争议：**c29“便宜运动鞋”没有数值预算，第五课标签却用 `max_price=200` 定义 `s01,s05`。新 Parser 不会编造 200 元上限，结果 `s05,s01,s03` 含一件按原标签计算的误召回，所以“标注约束满足率”只有 0.9444；这不是明确硬约束违规。c13 的 `s03` 只明确写“夏季”，没有“通勤”；c14 的 `s06` 写“竞速”，没有明确“跑步”。本课保留原标签和基线，建议下次另建标注版本并由人工复核。当前排序仍受固定合成目录影响，不能代表 Go API 的相关度排序。

下一步优先处理标签复核和软需求门槛的误删风险，再扩充真实查询样本。不要用本课 30 条样本反复调词表到“满分”。

运行命令：

```bash
python agent-service/evals/run_retrieval_comparison.py
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py agent-service/examples/test_real_llm.py agent-service/examples/test_product_api_tools.py agent-service/evals/test_retrieval_metrics.py agent-service/evals/test_retrieval_eval.py agent-service/evals/test_query_parser.py agent-service/evals/test_improved_retrieval.py -q
```

## 五道面试题

1. **Parser 和 Rewrite 有何区别？** Parser 提取字段和约束；Rewrite 改写检索词。两者可配合，但输出与责任不同。
2. **为什么“便宜”不能直接当 200 元硬约束？** 用户没有提供数值，随意设阈值会错误过滤商品，应只当软偏好或追问预算。
3. **为什么过滤要先于 Top-K？** 不合格候选若先占满 K，符合约束的商品可能被截掉。
4. **同义词为什么可能伤害 Precision？** 扩展扩大候选范围，相关和不相关商品都可能进入，需要字段约束与复核。
5. **指标升高就能证明线上效果好吗？** 不能。这里只用 12 件合成商品和 30 条固定样本，且基线和新方案的查询输入难度不同；还需真实数据和人工标签验证。
