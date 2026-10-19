# ShopPilot 第六课检索对比

固定合成数据；新方案只以原始 Query 和商品目录作为推理输入。第五课报告保持不变。

| 指标 | 第五课 | 第六课 |
| --- | ---: | ---: |
| precision_at_k | 0.3086 | 0.5062 |
| recall_at_k | 0.6173 | 0.9815 |
| hit_at_k | 0.6667 | 1.0 |
| mrr | 0.642 | 1.0 |
| ndcg_at_k | 0.6323 | 1.0 |
| explicit_hard_constraint_satisfaction_rate | 0.8333 | 1.0 |
| hard_constraint_satisfaction_rate | 0.7222 | 0.9444 |
| false_positive_at_k | 5 | 1 |
| correct_rejection_rate | 1.0 | 1.0 |

回退案例：无

## 重点案例

| ID | Query | 基线 Top-3 | 改进 Top-3 | Recall 变化 |
| --- | --- | --- | --- | ---: |
| c13 | 夏天通勤穿的鞋 |  | s01, s03 | 1.0 |
| c17 | 跑鞋 |  | s02, s06 | 1.0 |
| c21 | 迅步运动鞋 | s01, s02, s03 | s01, s02, s06 | 0.3333 |
| c22 | 飞跃运动鞋 | s01, s02, s03 | s03, s04 | 0.5 |
| c24 | 迅步运动鞋预算300元 | s01, s03, s05 | s01 | 0.0 |

## 全部样本

| ID | 基线 Top-3 | 改进 Top-3 | Recall@3 变化 | 回退 |
| --- | --- | --- | ---: | --- |
| c01 | s01 | s01 | 0.0 | False |
| c02 | s02 | s02 | 0.0 | False |
| c03 | s07 | s07 | 0.0 | False |
| c04 | s10 | s10 | 0.0 | False |
| c05 | s09 | s09 | 0.0 | False |
| c06 | s01, s02, s03 | s01, s02, s03 | 0.0 | False |
| c07 | s07, s08 | s07, s08 | 0.0 | False |
| c08 | s10, s11 | s10, s11 | 0.0 | False |
| c09 | s01, s05 | s01, s05 | 0.0 | False |
| c10 | s07 | s07 | 0.0 | False |
| c11 | s11 | s11 | 0.0 | False |
| c12 | s09 | s09 | 0.0 | False |
| c13 |  | s01, s03 | 1.0 | False |
| c14 |  | s02, s06 | 1.0 | False |
| c15 |  | s07 | 1.0 | False |
| c16 |  | s11 | 1.0 | False |
| c17 |  | s02, s06 | 1.0 | False |
| c18 |  | s04 | 1.0 | False |
| c19 |  | s10, s11 | 1.0 | False |
| c20 |  | s07 | 1.0 | False |
| c21 | s01, s02, s03 | s01, s02, s06 | 0.3333 | False |
| c22 | s01, s02, s03 | s03, s04 | 0.5 | False |
| c23 | s10, s11 | s10, s11 | 0.0 | False |
| c24 | s01, s03, s05 | s01 | 0.0 | False |
| c25 | s04 | s04 | 0.0 | False |
| c26 |  |  | None | False |
| c27 |  |  | None | False |
| c28 |  |  | None | False |
| c29 |  | s05, s01, s03 | 1.0 | False |
| c30 | s09 | s09 | 0.0 | False |
