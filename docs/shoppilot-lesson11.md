# ShopPilot 第十一课：真实 Embedding 与 Hybrid Search 评测

## 已有模块和输入输出

本课继续使用第五课固定的 **12 件合成商品、30 条 Query、人工相关商品 ID**，以及同一套 `K=3` 指标。合成数据不代表线上商品。第五课的 Keyword Baseline 使用预先标记的关键词和 fixture 顺序，原报告没有查询耗时；第六课 `parse_query(raw_query)` 输出关键词、类别、品牌、预算、软需求和诊断，`retrieve()` 执行规则召回、硬约束过滤与软需求排序。第七课 `SemanticIndex` 用商品的名称、类别、品牌、卖点构成文本，调用 Embedder 生成商品向量；查询文本单独生成向量，经归一化后的余弦相似度得到 Vector 排名。`hybrid_search()` 复用规则候选与向量候选，以 RRF 合并排名，再过滤硬约束，可选确定性 Rerank。

```text
原始 Query + 合成商品
  ├─ Keyword：第五课冻结 Top-3（fixture 顺序，无相关度排序承诺）
  ├─ Rule：Query Parser → 关键词/同义词 → 硬过滤 → 软需求排序
  ├─ Vector：商品与 Query 的真实 Embedding → 余弦相似度 → Top-3
  └─ Hybrid：Rule 候选 + Vector 候选 → RRF → 硬过滤 → [Rerank] → Top-3
Top-3 + 人工标签 → Precision@3、Recall@3、Hit@3、MRR、NDCG@3
```

Embedding 的输入是文本，输出是固定维度的浮点向量。余弦相似度是两向量点积除以各自长度；方向更接近时分数更高。RRF 只使用两个检索列表中的排名，按 `1/(60+rank)` 给每个商品累计分数，不要求原分数同尺度。Rerank 在已融合且满足硬约束的候选上按软需求、关键词命中和低价信号再次排序；它不增加候选，因而不能弥补两路都没召回的商品。第七课字符哈希 Mock 只是协议测试，绝非真实语义模型。

## 独立真实模型运行

新入口是 `agent-service/evals/run_real_embedding_eval.py`，默认选择轻量多语言模型 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，也接受 `--model` 指定本地目录或其他模型名。默认只读本地缓存；只有显式传入 `--download` 才允许下载。模型在 CPU 运行，不启动向量数据库。先在网络正常的环境显式安装可选依赖：

```powershell
python -m pip install -r agent-service/evals/requirements-real-embedding.txt
python agent-service/evals/run_real_embedding_eval.py --download
```

已有本地模型时：

```powershell
python agent-service/evals/run_real_embedding_eval.py --model D:\models\multilingual-embedding
```

真实运行后，JSON 和 Markdown 报告另存至 `agent-service/evals/reports/lesson11_real/`，文件名包含模型和 UTC 时间，使用排他创建，避免覆盖第五至第七课冻结报告。报告记录模型名、模型 revision（若可取得）、sentence-transformers 与 torch 版本、向量维度、设备、模型加载耗时、整体评测耗时、各方法单次查询耗时、数据与冻结报告 SHA-256，以及每条样本结果和失败分类。推理侧只用原始 Query 与商品目录；标签只用于事后评分。正例计算五项排序指标；空标签单独统计正确拒答率。Keyword 冻结报告没有计时，表中标为未测，不能与现测查询耗时直接比较。

## 已知基线与当前真实运行状态

历史冻结报告中的第五课 Keyword 指标为 Precision@3 **0.3086**、Recall@3 **0.6173**、Hit@3 **0.6667**、MRR **0.6420**、NDCG@3 **0.6323**。第六课冻结 Rule 指标为 Precision@3 **0.5062**、Recall@3 **0.9815**、Hit@3 **1.0**、MRR **1.0**、NDCG@3 **1.0**。新运行器的 Rule 列会使用当前已取消软需求硬门槛的代码重新计算，可能不同于冻结报告。第七课报告中 Vector、Hybrid、Hybrid+Rerank 的数值来自 **Mock 字符哈希**，此处不列为真实结果。

本机运行环境的 `sentence-transformers` 尚未安装：使用当前 pip 索引及官方 PyPI 安装均遇到 HTTP 响应截断，随后显式执行评测入口报 `ModuleNotFoundError`。因此**真实 Vector、Hybrid、Hybrid+Rerank 指标尚未产生**，模型版本、向量维度和实际模型耗时也尚未验证；不能宣称真实向量提升或下降。默认离线 pytest 运行结果为 **102 passed、1 条 Starlette TestClient 弃用警告**。安装问题解决后，应实际运行命令并阅读新生成报告，再将真实结果与规则方案比较；即使 Hybrid 更差也保留原值。

## c13、c16、c29 的检查重点

- **c13“夏天通勤穿的鞋”**：冻结 Keyword 无结果，Rule 召回 `s01、s03`。真实向量是否能把两件商品排进 Top-3 尚未知。若候选未出现是召回问题；若候选存在但不在 Top-3 是排序问题。
- **c16“打字不吵的设备”**：冻结 Keyword 无结果，Rule 召回 `s11`。真实向量需捕捉“不吵”与静音键盘的语义关系；若 Hybrid 候选已有 `s11` 却掉出 Top-3，应检查融合或重排，而非误称没有召回。
- **c29“便宜运动鞋但最多看一页”**：原句没有明确 200 元预算，原人工标签却包含该隐含门槛，并带分页条件。这是标签与输入不一致的争议，不能通过偷加 200 元过滤来提高分数。报告保留原标签并单独标注争议。真实向量不能修复标签定义或第五课分页设置。

硬约束过滤失败指解析出的品牌、类别或预算排除了标签商品；应同时审查解析与标签。所有方法都在相同固定商品和标签上评测，但基线查询已预标关键词、当前方法从原句解析，比较仍有方法学局限。小数据集和人工标签可能放大个别案例影响，需要在真实匿名查询上另建版本化评测集后再推广结论。
