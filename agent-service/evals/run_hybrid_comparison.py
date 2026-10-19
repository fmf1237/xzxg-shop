"""第五、六课冻结报告 + 新检索器的独立对比；默认向量仅为 Mock 协议验证。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
from time import perf_counter_ns

from hybrid_retrieval import hybrid_search
from improved_retrieval import retrieve
from query_parser import catalog_metadata, parse_query
from retrieval_metrics import all_metrics
from run_retrieval_eval import ROOT, load_data
from semantic_retrieval import LocalSentenceTransformerEmbedder, MockEmbedder, SemanticIndex


METHODS = ("keyword_baseline", "lesson06_rule", "vector", "hybrid", "hybrid_rerank")
BASELINE = ROOT / "reports" / "retrieval_baseline.json"
LESSON06 = ROOT / "reports" / "retrieval_comparison.json"


def _summary(rows, method, products):
    relevant = [row for row in rows if row["expected_product_ids"]]
    negative = [row for row in rows if not row["expected_product_ids"]]
    metrics = {name: round(sum(row["results"][method]["metrics"][name] for row in relevant) / len(relevant), 4) for name in ("recall_at_k", "hit_at_k", "mrr", "ndcg_at_k")}
    metrics["correct_rejection_rate"] = round(sum(not row["results"][method]["ids"] for row in negative) / len(negative), 4)
    by_id = {product["id"]: product for product in products}
    checks = []
    for row in rows:
        parsed = row["parsed_query"]
        if not (parsed["brand"] or parsed["category"] or parsed["max_price"] is not None):
            continue
        for product_id in row["results"][method]["ids"]:
            product = by_id[product_id]
            checks.append((not parsed["brand"] or product["brand"] == parsed["brand"]) and (not parsed["category"] or product["category"] == parsed["category"]) and (parsed["max_price"] is None or Decimal(product["price"]) <= parsed["max_price"]))
    metrics["hard_constraint_satisfaction_rate"] = round(sum(checks) / len(checks), 4) if checks else None
    timings = [row["results"][method]["elapsed_ms"] for row in rows if row["results"][method]["elapsed_ms"] is not None]
    metrics["mean_query_ms"] = round(sum(timings) / len(timings), 4) if timings else None
    return metrics


def compare(products, cases, baseline, lesson06, embedder):
    case_ids = [case["case_id"] for case in cases]
    if baseline["k"] != lesson06["k"] or baseline["k"] != 3 or [row["case_id"] for row in baseline["cases"]] != case_ids or [row["case_id"] for row in lesson06["cases"]] != case_ids:
        raise ValueError("冻结报告与当前样本或 K 不一致")
    metadata = catalog_metadata(products)
    index = SemanticIndex(products, embedder)
    rows = []
    for case, old, sixth in zip(cases, baseline["cases"], lesson06["cases"]):
        # 推理只用原始 query、目录和 Embedding；标签仅在结果产生后用于评分。
        parsed = parse_query(case["query"], metadata)
        started_rule = perf_counter_ns()
        rule_ids, rule_trace = retrieve(products, parsed, k=3)
        results = {
            "keyword_baseline": {"ids": old["top_k_product_ids"], "trace": None, "elapsed_ms": None},
            "lesson06_rule": {"ids": rule_ids, "trace": rule_trace, "elapsed_ms": round((perf_counter_ns() - started_rule) / 1_000_000, 4)},
        }
        for name in ("vector", "hybrid", "hybrid_rerank"):
            started = perf_counter_ns()
            if name == "vector":
                vector = index.search(case["query"], k=3)
                ids, trace = [item["id"] for item in vector], {"vector": vector, "embedding_kind": embedder.kind}
            else:
                ids, trace = hybrid_search(products, parsed, case["query"], index, k=3, rerank=name == "hybrid_rerank")
            results[name] = {"ids": ids, "trace": trace, "elapsed_ms": round((perf_counter_ns() - started) / 1_000_000, 4)}
        expected = case["expected_product_ids"]
        for result in results.values():
            result["metrics"] = all_metrics(result["ids"], expected, 3)
        rows.append({"case_id": case["case_id"], "query": case["query"], "expected_product_ids": expected, "parsed_query": parsed, "lesson06_frozen_ids": sixth["improved_ids"], "results": results})
    summary = {method: _summary(rows, method, products) for method in METHODS}
    regressions = {method: [row["case_id"] for row in rows if row["expected_product_ids"] and row["results"][method]["metrics"]["recall_at_k"] < row["results"]["lesson06_rule"]["metrics"]["recall_at_k"]] for method in ("vector", "hybrid", "hybrid_rerank")}
    return {"dataset_type": "synthetic_test_data", "embedding_kind": embedder.kind, "evidence_level": "mock_protocol_only" if embedder.kind.startswith("mock") else "local_real_embedding", "k": 3, "lesson06_frozen_source": str(LESSON06.relative_to(ROOT)), "lesson06_note": "规则列使用取消软门槛后的当前代码重新运行；原第六课报告保持冻结", "label_review": ["c29：原句‘便宜运动鞋但最多看一页’没有数值预算，旧标签却采用 max_price=200；本次不修改标签或旧分页报告"], "timing_note": "仅当前规则和向量/Hybrid 方法测量单次查询；不含模型加载和建索引；第五课冻结报告无耗时，None 表示未测", "summary": summary, "regressions_vs_lesson06": regressions, "cases": rows}


def markdown_report(report):
    lines = ["# ShopPilot 第七课独立对比", "", f'Embedding：`{report["embedding_kind"]}`；证据等级：`{report["evidence_level"]}`。', "", "固定合成商品与 30 条 Query。Mock 字符哈希仅验证协议，不证明语义检索优于规则方案。", "", "| 方法 | Recall@3 | Hit@3 | MRR | NDCG@3 | 硬约束满足率 | 平均查询 ms |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for method in METHODS:
        s = report["summary"][method]
        lines.append(f'| {method} | {s["recall_at_k"]} | {s["hit_at_k"]} | {s["mrr"]} | {s["ndcg_at_k"]} | {s["hard_constraint_satisfaction_rate"]} | {s["mean_query_ms"]} |')
    lines += ["", "## 回退与失败", "", *[f'- 标签争议：{note}' for note in report["label_review"]]]
    for method, ids in report["regressions_vs_lesson06"].items():
        lines.append(f'- {method} 相对第六课 Recall@3 回退：{", ".join(ids) or "无"}')
    lines += ["", "## 逐条结果", "", "| ID | Query | 期望 | Baseline | Rule | Vector | Hybrid | Hybrid+Rerank |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["cases"]:
        ids = [", ".join(row["results"][method]["ids"]) for method in METHODS]
        lines.append(f'| {row["case_id"]} | {row["query"]} | {", ".join(row["expected_product_ids"])} | ' + " | ".join(ids) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-model", type=Path, help="已下载的本地 sentence-transformers 模型目录；省略则使用 Mock")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    products, cases = load_data()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    lesson06 = json.loads(LESSON06.read_text(encoding="utf-8"))
    embedder = LocalSentenceTransformerEmbedder(args.local_model) if args.local_model else MockEmbedder()
    report = compare(products, cases, baseline, lesson06, embedder)
    suffix = "real" if args.local_model else "mock"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"retrieval_lesson07_{suffix}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / f"retrieval_lesson07_{suffix}.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"embedding_kind": embedder.kind, "summary": report["summary"], "regressions": report["regressions_vs_lesson06"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
