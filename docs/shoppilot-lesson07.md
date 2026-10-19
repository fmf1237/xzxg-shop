# ShopPilot 第七课：Embedding、Hybrid Search 与 Rerank

## 原项目已经有什么

Go 项目的 `backend/src/rag/vector_embedder.go` 已实现 OpenAI-compatible Embedding 请求，`vector_milvus.go` 已支持商品向量搜索。`backend/src/store/mysql.go` 的 `SearchProductsLimit` 先取关键词商品，向量服务可用时合并向量候选，再调用规则排序。`backend/src/agent/tools.go` 的 `toolSearchProducts` 还会执行结构化约束、模型或规则重排、相关性处理和 Trace。本课 Python 代码是**独立、离线的教学对照实验**，不是为 Go 后端首次设计这些能力。

## 五层检索流水线

[`semantic_retrieval.py`](../agent-service/evals/semantic_retrieval.py) 把商品名称、类别、品牌、卖点拼成向量文本。Embedding 输入是文字列表，输出是等长的浮点向量列表；`SemanticIndex` 将向量归一化，查询时算余弦相似度并返回 `id`、`score`。余弦公式是 `A·B / (|A||B|)`：例如 `[1,0]` 与 `[0,1]` 为 0，同方向向量为 1。向量维度不一致或零向量会报错。

`MockEmbedder` 用字符哈希桶生成固定向量，**没有训练、没有真正语义泛化**，只用于离线测试协议、归一化、融合和 Trace。若已在本机准备好 sentence-transformers 模型目录，可显式选择 `LocalSentenceTransformerEmbedder`；当前环境没有该包或本地模型，因此没有真实 Embedding 结果。小规模商品直接在内存算相似度，不启动 Milvus。

[`hybrid_retrieval.py`](../agent-service/evals/hybrid_retrieval.py) 的每层输入输出：

| 层 | 输入 | 输出 |
| --- | --- | --- |
| Keyword | Parser 结构化查询和商品目录 | 第六课关键词候选 ID |
| Vector | 原始 Query 和商品向量 | 带相似度的候选 ID |
| Fusion | 两组排名 | 按 ID 去重、带 RRF 分数的候选 |
| Filter | 融合候选和明确的品牌、类别、数字预算 | 保留商品及逐项过滤原因 |
| Rerank | 过滤后的商品、软需求、关键词和 RRF 分数 | 可解释的最终顺序与 Top-K |

RRF（Reciprocal Rank Fusion）给每个候选在每张榜单上的排名加 `1/(60+rank)`，两张榜单的分数相加。它只用名次，不要求关键词分数和余弦分数有相同量纲。Rerank 则对**已有候选**重新排序，本课加上软需求命中、关键词命中及“低价”偏好；它不能找回两个召回器都没找到的商品。硬约束在最终 Top-K 之前执行，否则不合格商品会占掉位置。

第六课 `improved_retrieval.py` 原本把软需求命中当作门槛。本课已取消该门槛：对于类别、品牌等硬约束得到的候选，即使软需求没有命中也保留，只改变其排序。没有其他检索锚点时，软词仍可帮助建立候选；这不等同于把明确硬约束合格商品删除。

## 可复现实验与边界

运行：

```bash
python agent-service/evals/run_hybrid_comparison.py
```

默认只生成 [Mock JSON](../agent-service/evals/reports/retrieval_lesson07_mock.json) 和 [Mock Markdown](../agent-service/evals/reports/retrieval_lesson07_mock.md)。若另行安装 sentence-transformers 并准备本地模型，可运行 `python agent-service/evals/run_hybrid_comparison.py --local-model 模型目录`，结果写入单独的 `_real` 报告；不会覆盖 Mock、第六课或第五课报告。

本次在 12 件**合成商品**、30 条固定 Query、K=3 下运行，结果如下。除第五课冻结基线外，其余方法的查询耗时只计本地单次搜索，不含模型加载或建索引；毫秒数受机器影响，不能跨环境直接比较。

| 方法 | Recall@3 | Hit@3 | MRR | NDCG@3 | 明确硬约束满足率 | 正确拒答率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 第五课 Keyword Baseline | 0.6173 | 0.6667 | 0.6420 | 0.6323 | 0.8333 | 1.0000 |
| 修正后的第六课规则检索 | 0.9815 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| Vector（**Mock**） | 0.7593 | 0.8519 | 0.7901 | 0.7611 | 0.5467 | 0.0000 |
| Hybrid（**Mock**） | 0.9259 | 0.9630 | 0.9444 | 0.9313 | 1.0000 | 0.6667 |
| Hybrid + Rerank（**Mock**） | 0.9815 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.6667 |

这些 Mock 数值只说明流水线行为，**不能声称真实语义检索优于或弱于规则方案**。Vector 在 c09、c13、c14、c15、c16、c17、c19、c29 相对规则检索有 Recall 回退；Hybrid 在 c16、c29 回退；Hybrid + Rerank 没有 Recall 回退，但无匹配查询仍有误召回。原因是假向量对陌生词也会给商品一个相似度，RRF 会将其纳入候选，重排无法解决“本应拒答”的问题。下一步应独立研究候选置信度与拒答策略，并在真实模型和真实查询上复测。

**c29 单独记录：**第五课样本把“便宜”标为 `max_price=200`，原句却没有数值预算；第五课还人为限制只看一页。本课保留原标签与旧报告，不把“便宜”硬解释为 200 元，也不复写旧分页限制。当前比较因此包含标注与协议差异，后续应在人审后另建标签版本。

## 测试

```bash
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py agent-service/examples/test_real_llm.py agent-service/examples/test_product_api_tools.py agent-service/evals/test_retrieval_metrics.py agent-service/evals/test_retrieval_eval.py agent-service/evals/test_query_parser.py agent-service/evals/test_improved_retrieval.py agent-service/evals/test_semantic_retrieval.py agent-service/evals/test_hybrid_retrieval.py -q
```

## 五道面试题

1. **Embedding 输入输出是什么？** 输入文本，输出固定维度向量；向量是否表达语义取决于训练过的模型，字符哈希 Mock 不算语义模型。
2. **余弦相似度的作用是什么？** 比较向量方向，常用于向量检索；需处理零向量和维度不一致。
3. **RRF 为什么适合融合？** 它用排名而非原始分数，避免直接相加量纲不同的关键词分数和向量分数。
4. **Rerank 能提高 Recall 吗？** 它只能重排已有候选；若相关商品未被召回，单独重排无法找回。
5. **为什么 Hybrid 仍需硬过滤和拒答？** 融合扩大候选池，也会带来不符合约束或本不该返回的商品；必须先筛硬条件并评估无匹配情况。
