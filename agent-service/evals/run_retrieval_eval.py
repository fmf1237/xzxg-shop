"""固定数据的离线关键词评测；不调用 Go、MySQL、模型或网络。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path

from retrieval_metrics import all_metrics


ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"


def load_data(products_path=FIXTURES / "products.json", cases_path=FIXTURES / "search_cases.jsonl"):
    data = json.loads(Path(products_path).read_text(encoding="utf-8"))
    if data.get("dataset_type") != "synthetic_test_data":
        raise ValueError("必须明确标记为合成测试数据")
    products = data["products"]
    cases = [json.loads(line) for line in Path(cases_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [p["id"] for p in products]
    if len(ids) != len(set(ids)) or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("商品或样本 ID 重复")
    for case in cases:
        if not set(case["expected_product_ids"]) <= set(ids):
            raise ValueError(f'{case["case_id"]} 标准答案不在商品测试集中')
    return products, cases


def keyword_search(products, keyword, max_price=None, page_size=100, max_pages=20):
    """单一子串匹配 + 价格过滤；保留 fixture 顺序，只作分页诊断。"""
    text = keyword.strip().casefold()
    candidates = [
        p for p in products
        if text and (
            any(text in str(p[field]).casefold() for field in ("name", "category", "brand"))
            or any(text in point.casefold() for point in p["selling_points"])
        )
    ]
    if len(candidates) > page_size * max_pages:
        return [], "pagination_limit"
    budget = Decimal(max_price) if max_price is not None else None
    return [p["id"] for p in candidates if budget is None or Decimal(p["price"]) <= budget], None


def explain(case, actual, all_products, error, k):
    expected = set(case["expected_product_ids"])
    if error == "pagination_limit":
        return "分页限制", "缩小检索词或提高安全分页上限，并完整读取结果"
    if not expected:
        if actual:
            return "无匹配误召回", "增加约束校验与拒答判断"
        if case["constraints"].get("max_price") is not None:
            return "正确拒答：预算下无商品", "解释价格门槛，避免虚构低价商品"
        return "正确拒答：数据中无商品", "确认商品库覆盖范围，不虚构商品"
    if expected <= set(actual[:k]) and set(actual[:k]) <= expected:
        return "通过", "保持现有基线"
    if not actual:
        if case["constraints"].get("max_price") is not None:
            unfiltered, _ = keyword_search(all_products, case["constraints"]["keyword"])
            if unfiltered:
                return "预算过滤后为空", "确认预算约束与实际价格；向用户解释价格门槛"
        if case["test_type"] == "synonym":
            return "同义词无法召回", "建立可审核的同义词表并比较召回变化"
        return "关键词完全不匹配", "分析用户表述与商品名称/卖点的词汇差异"
    if case["constraints"].get("brand") and set(actual[:k]) - expected:
        return "多条件约束不足", "在候选过滤中显式执行品牌约束"
    if expected - set(actual[:k]):
        return "检索结果不完整", "检查 Top-K 截断与候选覆盖率"
    return "误召回", "检查匹配字段与约束"


def evaluate(products, cases, k=3):
    rows = []
    for case in cases:
        constraints = case["constraints"]
        actual, error = keyword_search(products, constraints["keyword"], constraints.get("max_price"), constraints.get("page_size", 100), constraints.get("max_pages", 20))
        metrics = all_metrics(actual, case["expected_product_ids"], k)
        reason, recommendation = explain(case, actual, products, error, k)
        rows.append({"case_id": case["case_id"], "query": case["query"], "test_type": case["test_type"], "expected_product_ids": case["expected_product_ids"], "retrieved_product_ids": actual, "top_k_product_ids": actual[:k], "metrics": metrics, "failure_category": reason, "recommendation": recommendation, "error": error})
    positive = [r for r in rows if r["expected_product_ids"]]
    negative = [r for r in rows if not r["expected_product_ids"]]
    names = ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k")
    summary = {name: round(sum(r["metrics"][name] for r in positive) / len(positive), 4) if positive else None for name in names}
    summary.update({"total_cases": len(rows), "positive_cases": len(positive), "no_match_cases": len(negative), "correct_rejection_rate": round(sum(not r["retrieved_product_ids"] and not r["error"] for r in negative) / len(negative), 4) if negative else None, "failure_cases": sum(not r["failure_category"].startswith("正确拒答") and r["failure_category"] != "通过" for r in rows)})
    return {"dataset_type": "synthetic_test_data", "baseline": "single-substring-offline-keyword", "ordering_note": "fixture 固定顺序，仅用于可重复的 Top-K 诊断，不代表 Go API 或模型相关度排序", "k": k, "summary": summary, "cases": rows}


def markdown_report(report):
    s = report["summary"]
    lines = ["# ShopPilot 第五课离线检索基线", "", "数据：合成测试商品；不是线上商品。排序：fixture 固定顺序，不代表相关度。", "", f'K={report["k"]}；总样本={s["total_cases"]}；正例={s["positive_cases"]}；无匹配={s["no_match_cases"]}。', "", "| 指标 | 值 |", "| --- | ---: |"]
    for key in ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k", "correct_rejection_rate"):
        lines.append(f'| {key} | {s[key]} |')
    lines += ["", "## 逐条结果", "", "| ID | Query | 期望 | 检索 Top-K | Recall@K | 失败分类 | 建议 |", "| --- | --- | --- | --- | ---: | --- | --- |"]
    for row in report["cases"]:
        lines.append(f'| {row["case_id"]} | {row["query"]} | {", ".join(row["expected_product_ids"])} | {", ".join(row["top_k_product_ids"])} | {row["metrics"]["recall_at_k"]} | {row["failure_category"]} | {row["recommendation"]} |')
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("K 必须为正整数")
    products, cases = load_data()
    report = evaluate(products, cases, args.k)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "retrieval_baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "retrieval_baseline.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
