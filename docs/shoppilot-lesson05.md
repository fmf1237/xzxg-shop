# ShopPilot 第五课：商品检索评测与失败分析

## 先分清检索与生成

**检索**从已有商品中找 ID 和事实；**生成**将查到的事实组织成用户能读懂的回答。检索漏掉商品，生成阶段通常无法凭空补救；即使回答流畅，也不能证明推荐准确。RAG 的基本做法是先检索相关资料，再把检索结果交给模型生成回答。本课只建立检索基线，不实现新的 RAG 系统。

项目已存在 `quality/evals/run_product_search_eval.mjs` 和 `quality/evals/run_rag_recall_eval.mjs`，它们调用 Go 评测接口。Go 的 `SearchProductsLimit` 会组合关键词和可用的向量召回，再调用排序逻辑；公开 `/api/v1/products` 则使用关键词、分页和数据库排序。`backend/src/rag/` 已有分词、排序和向量相关代码。本课离线脚本既不替代这些在线评测，也不模拟其完整排序。

## 数据、标签和基线

[`products.json`](../agent-service/evals/fixtures/products.json) 有 12 件**合成测试商品**，不是线上或 MySQL 实际商品。[`search_cases.jsonl`](../agent-service/evals/fixtures/search_cases.jsonl) 有 30 条固定 Query，其中 27 条有相关商品，3 条期望无匹配。每条都写明 `case_id`、用户 `query`、标准答案 ID、约束和测试类型。标签依据商品名称、类别、品牌、价格与卖点人工核对；例如 `s04` 是飞跃品牌、防水运动鞋、329 元，因此符合“飞跃防水运动鞋预算350元”。

[`run_retrieval_eval.py`](../agent-service/evals/run_retrieval_eval.py) 用 `constraints.keyword` 作为给检索器的关键词。它是人工提供的抽取结果，用于隔离检索问题；这**不是**端到端测试 Planner 能否从用户原句抽出关键词。离线基线对名称、类别、品牌和卖点做单一子串匹配，再用 Decimal 过滤预算。它比 Go `productListQuery` 的中文分词和多字段 SQL 匹配更简单，也没有向量召回、排序或真实分页。品牌约束暂不执行，故能观察多条件错误。分页上限由本地模拟，超限明确报错。

检索结果保持 fixture 的固定顺序，只是为了每次跑出相同的 Top-K。公开 Go API 按 `sort_order, product_id` 分页，不承诺相关度排序；因此本报告中的 MRR/NDCG **只描述固定基线顺序**，不能解释为模型排序能力。

## 指标怎么算

设 Top-K 返回 `[x, b, a]`，相关商品为 `{a, b}`，K=3：

| 指标 | 含义与公式 | 例子输出 |
| --- | --- | ---: |
| Precision@K | Top-K 中相关数量 ÷ K | 2/3 |
| Recall@K | Top-K 中相关数量 ÷ 全部相关数量 | 2/2=1 |
| Hit@K | Top-K 是否至少有一个相关商品 | 1 |
| MRR | 第一个相关商品排名的倒数；没有命中为 0 | 1/2 |
| NDCG@K | DCG/理想 DCG；二元相关时 DCG=Σ相关位置的 1/log₂(排名+1) | (1/log₂3 + 1/log₂4)/(1 + 1/log₂3)≈0.693 |

这些函数都输入有序结果 ID、标准答案 ID 和 K，输出 0～1 浮点数。Precision@K 分母固定为 K，即使返回结果不足 K，也按 K 计。标准答案为空的 Query，五个指标返回 `None`，不纳入正例均值；它们单独统计“正确拒答率”。这样不会把“无商品且返回空”误算成高召回。

## 实际基线与失败分析

运行 `python agent-service/evals/run_retrieval_eval.py`，生成固定的 [JSON 报告](../agent-service/evals/reports/retrieval_baseline.json) 和 [Markdown 报告](../agent-service/evals/reports/retrieval_baseline.md)。本次 K=3：Precision@3=0.3086，Recall@3=0.6173，Hit@3=0.6667，MRR=0.642，NDCG@3=0.6323；3 条无匹配样本的正确拒答率为 1.0。低 Precision 的一个原因是分母固定为 3，而不少精确查询只返回 1 件相关商品。报告保留每条 Query 的完整检索 ID、Top-K、指标、失败分类与建议。

| 案例 | 观察 | 原因假设 | 下一步 |
| --- | --- | --- | --- |
| c13“夏天通勤穿的鞋” | 应找到 s01/s03，实际为空 | 整句与字段不构成子串 | 做查询词抽取，记录抽取前后召回 |
| c17“跑鞋” | 应找到 s02/s06，实际为空 | “跑鞋”与“运动鞋”词面不同 | 加受控同义词表，检查误召回 |
| c21“迅步运动鞋” | Top-3 混入飞跃商品 | 品牌约束未执行 | 显式品牌过滤并复测 |
| c06“运动鞋” | 6 件相关，Top-3 只有 3 件 | K 截断造成结果不完整 | 比较不同 K 的 Recall，按需求选择 K |
| c29“便宜运动鞋但最多看一页” | 返回 `pagination_limit` | 候选数超过模拟页数上限 | 完整读取或缩小关键词，不报告部分结果 |
| c26“敏感肌面霜预算200元” | 正确返回空 | 唯一相符商品 299 元，预算不足 | 明确告知预算门槛，不编造低价商品 |
| c27“无人机” | 正确返回空 | 固定商品集中没有无人机 | 记录商品覆盖缺口，向用户说明无货 |

当前失败分类是**原因假设**，不是线上故障根因。若下一阶段尝试 Embedding，它可以帮助召回词面不同但语义接近的商品；Rerank 可将候选按用户需求重新排序。但先应修复查询抽取、品牌约束与分页完整性，再用同一套数据比较新增方法的收益和误召回。

## 怎样公平、可重复

固定商品和标签、固定 Top-K、固定排序与预算处理规则；每次保存逐条结果和指标，比较同一批 Query。调整同义词、Embedding 或 Rerank 时，保留原始基线报告；若扩充商品或重标答案，另设数据版本。合成数据只能证明实现和实验方法可重复，不能代表真实用户分布或线上效果。面向线上效果还需匿名真实查询、人工复核标签以及与 Go 当前在线评测并行比较。

运行全部五课测试：

```bash
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py agent-service/examples/test_real_llm.py agent-service/examples/test_product_api_tools.py agent-service/evals/test_retrieval_metrics.py agent-service/evals/test_retrieval_eval.py -q
```

## 五道面试题

1. **Recall@K 低说明什么？** 有标准答案商品没进入前 K；可能是查询词、召回范围、约束或 K 的问题。
2. **MRR 和 Recall@K 有何区别？** MRR 关注第一个相关结果出现得多早；Recall@K 关注相关商品覆盖了多少。
3. **无结果 Query 为什么不计入 Recall 均值？** 标准答案为空，分母为零；应另算正确拒答率与误召回率。
4. **Embedding 与 Rerank 分别做什么？** Embedding 帮助找语义相近候选；Rerank 对已有候选重新排序，无法找回从未召回的商品。
5. **为什么固定数据和顺序？** 保证重复运行与方案比较不被数据变化影响；同时要说明固定顺序不等于相关度排名。
