"""用原始 query 对照第五课冻结基线，不读取标签/约束来做新方案推理。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path

from improved_retrieval import retrieve
from query_parser import catalog_metadata, parse_query
from retrieval_metrics import all_metrics
from run_retrieval_eval import ROOT, load_data


BASELINE = ROOT / "reports" / "retrieval_baseline.json"
METRIC_NAMES = ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k")
FOCUS = ("c13", "c17", "c21", "c22", "c24")


def _summary(rows, key, cases, by_id):
    ids_key = "baseline_ids" if key == "baseline_metrics" else "improved_ids"
    positive = [row for row in rows if row["expected_product_ids"]]
    negative = [row for row in rows if not row["expected_product_ids"]]
    metrics = {name: round(sum(row[key][name] for row in positive) / len(positive), 4) for name in METRIC_NAMES}
    metrics["correct_rejection_rate"] = round(sum(not row[ids_key] for row in negative) / len(negative), 4)
    metrics["false_positive_at_k"] = sum(len(set(row[ids_key]) - set(row["expected_product_ids"])) for row in rows)
    checks = []
    case_by_id = {case["case_id"]: case for case in cases}
    for row in rows:
        constraints = case_by_id[row["case_id"]]["constraints"]
        if not (constraints.get("brand") or constraints.get("max_price")):
            continue
        for product_id in row[ids_key]:
            product = by_id[product_id]
            checks.append((not constraints.get("brand") or product["brand"] == constraints["brand"]) and (constraints.get("max_price") is None or Decimal(product["price"]) <= constraints["max_price"]))
    metrics["hard_constraint_satisfaction_rate"] = round(sum(checks) / len(checks), 4) if checks else None
    metrics["hard_constraint_checked_items"] = len(checks)
    explicit_checks = []
    metadata = catalog_metadata(list(by_id.values()))
    for row in rows:
        parsed = parse_query(row["query"], metadata)
        if not (parsed["brand"] or parsed["category"] or parsed["max_price"] is not None):
            continue
        for product_id in row[ids_key]:
            product = by_id[product_id]
            explicit_checks.append(
                (not parsed["brand"] or product["brand"] == parsed["brand"])
                and (not parsed["category"] or product["category"] == parsed["category"])
                and (parsed["max_price"] is None or Decimal(product["price"]) <= parsed["max_price"])
            )
    metrics["explicit_hard_constraint_satisfaction_rate"] = round(sum(explicit_checks) / len(explicit_checks), 4) if explicit_checks else None
    metrics["explicit_hard_constraint_checked_items"] = len(explicit_checks)
    return metrics


def compare(products, cases, baseline):
    if baseline["k"] != 3 or [row["case_id"] for row in baseline["cases"]] != [case["case_id"] for case in cases]:
        raise ValueError("冻结基线与当前样本或 K 不一致")
    metadata = catalog_metadata(products)
    by_id = {product["id"]: product for product in products}
    rows = []
    for case, old in zip(cases, baseline["cases"]):
        # 推理侧只使用 query 和 catalog；expected/constraints 在取结果后才用于评分。
        parsed = parse_query(case["query"], metadata)
        new_ids, trace = retrieve(products, parsed, k=3)
        expected = case["expected_product_ids"]
        old_ids = old["top_k_product_ids"]
        new_metrics = all_metrics(new_ids, expected, 3)
        old_metrics = all_metrics(old_ids, expected, 3)
        delta = {name: round(new_metrics[name] - old_metrics[name], 4) if expected else None for name in METRIC_NAMES}
        rows.append({"case_id": case["case_id"], "query": case["query"], "expected_product_ids": expected, "baseline_ids": old_ids, "improved_ids": new_ids, "baseline_metrics": old_metrics, "improved_metrics": new_metrics, "metric_delta": delta, "regressed": bool(expected and new_metrics["recall_at_k"] < old_metrics["recall_at_k"]), "trace": trace})
    return {
        "dataset_type": "synthetic_test_data",
        "k": 3,
        "baseline_source": str(BASELINE.relative_to(ROOT)),
        "inference_inputs": "raw query + catalog metadata/products only; labels and constraints used after retrieval for scoring",
        "baseline_summary": _summary(rows, "baseline_metrics", cases, by_id),
        "improved_summary": _summary(rows, "improved_metrics", cases, by_id),
        "regressions": [row["case_id"] for row in rows if row["regressed"]],
        "focus_cases": [row for row in rows if row["case_id"] in FOCUS],
        "cases": rows,
    }


def markdown_report(report):
    lines = ["# ShopPilot 第六课检索对比", "", "固定合成数据；新方案只以原始 Query 和商品目录作为推理输入。第五课报告保持不变。", "", "| 指标 | 第五课 | 第六课 |", "| --- | ---: | ---: |"]
    for name in (*METRIC_NAMES, "explicit_hard_constraint_satisfaction_rate", "hard_constraint_satisfaction_rate", "false_positive_at_k", "correct_rejection_rate"):
        lines.append(f'| {name} | {report["baseline_summary"][name]} | {report["improved_summary"][name]} |')
    lines += ["", f'回退案例：{", ".join(report["regressions"]) or "无"}', "", "## 重点案例", "", "| ID | Query | 基线 Top-3 | 改进 Top-3 | Recall 变化 |", "| --- | --- | --- | --- | ---: |"]
    for row in report["focus_cases"]:
        lines.append(f'| {row["case_id"]} | {row["query"]} | {", ".join(row["baseline_ids"])} | {", ".join(row["improved_ids"])} | {row["metric_delta"]["recall_at_k"]} |')
    lines += ["", "## 全部样本", "", "| ID | 基线 Top-3 | 改进 Top-3 | Recall@3 变化 | 回退 |", "| --- | --- | --- | ---: | --- |"]
    for row in report["cases"]:
        lines.append(f'| {row["case_id"]} | {", ".join(row["baseline_ids"])} | {", ".join(row["improved_ids"])} | {row["metric_delta"]["recall_at_k"]} | {row["regressed"]} |')
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    products, cases = load_data()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = compare(products, cases, baseline)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "retrieval_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "retrieval_comparison.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"baseline": report["baseline_summary"], "improved": report["improved_summary"], "regressions": report["regressions"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
