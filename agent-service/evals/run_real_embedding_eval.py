"""显式运行真实 CPU Embedding，对比冻结 Keyword 与现有 Rule/Hybrid。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter

from run_hybrid_comparison import BASELINE, LESSON06, METHODS, compare
from run_retrieval_eval import FIXTURES, ROOT, load_data


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
METRICS = ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k")
FOCUS = ("c13", "c16", "c29")


class RealSentenceTransformerEmbedder:
    kind = "real_sentence_transformer_cpu"

    def __init__(self, model_name, allow_download=False):
        try:
            import sentence_transformers
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("请显式安装 agent-service/evals/requirements-real-embedding.txt") from exc
        self.model_name = model_name
        self.package_version = sentence_transformers.__version__
        self.torch_version = torch.__version__
        self.device = "cpu"
        self.model = SentenceTransformer(model_name, device=self.device, local_files_only=not allow_download)
        self.dimensions = self.model.get_sentence_embedding_dimension()
        first = self.model._first_module() if hasattr(self.model, "_first_module") else None
        config = getattr(getattr(first, "auto_model", None), "config", None)
        self.model_revision = getattr(config, "_commit_hash", None)

    def encode(self, texts):
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False).tolist()


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mean(values):
    return round(sum(values) / len(values), 4) if values else None


def _failure_reason(row, method):
    expected = set(row["expected_product_ids"])
    if not expected:
        return "标签为空：单独统计正确拒答"
    result = row["results"][method]
    missed = expected - set(result["ids"])
    if not missed:
        return "Top-3 已召回全部标签"
    if method == "keyword_baseline":
        return "关键词召回或分页限制；冻结顺序无相关度承诺"
    if method == "lesson06_rule":
        trace = result["trace"]
        if missed & {item["id"] for item in trace["filtered"]}:
            return "约束过滤排除了标签商品"
        if missed & set(trace["candidates"]):
            return "候选已召回，但 Top-3 排序不足"
        return "规则候选未召回标签商品"
    if method == "vector":
        return "向量 Top-3 未召回标签商品；全量候选中的相似度排序不足"
    trace = result["trace"]
    if missed & {item["id"] for item in trace["filter"] if not item["kept"]}:
        return "硬约束过滤排除了标签商品，需检查解析或标签"
    if missed & {item["id"] for item in trace["fusion"]}:
        return "融合候选已包含标签商品，但 Top-3 排序不足"
    return "Keyword 与 Vector 候选均未召回标签商品"


def enrich_report(report, products, cases, embedder, model_load_ms, total_ms):
    """沿用第七课比较结果，补 Precision、模型元数据与诊断。"""
    if embedder.kind.startswith("mock"):
        raise ValueError("真实模型报告不能使用 Mock Embedding")
    positives = [row for row in report["cases"] if row["expected_product_ids"]]
    for method in METHODS:
        summary = report["summary"][method]
        summary["precision_at_k"] = _mean([row["results"][method]["metrics"]["precision_at_k"] for row in positives])
        summary["timing_scope"] = "not_measured_frozen_report" if method == "keyword_baseline" else "query_only_excludes_load_and_index"
    for row in report["cases"]:
        row["failure_analysis"] = {method: _failure_reason(row, method) for method in METHODS}
    report["lesson"] = 11
    report["embedding_kind"] = embedder.kind
    report["evidence_level"] = "real_local_cpu_embedding"
    report["model"] = {
        "name": embedder.model_name,
        "revision": embedder.model_revision,
        "sentence_transformers_version": embedder.package_version,
        "torch_version": embedder.torch_version,
        "dimensions": embedder.dimensions,
        "device": embedder.device,
    }
    report["run_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["model_load_ms"] = model_load_ms
    report["total_eval_ms"] = total_ms
    report["fixture_sha256"] = {path.name: _hash(path) for path in (FIXTURES / "products.json", FIXTURES / "search_cases.jsonl")}
    report["frozen_report_sha256"] = {path.name: _hash(path) for path in (BASELINE, LESSON06)}
    report["sample_size"] = {"products": len(products), "queries": len(cases)}
    report["focus_cases"] = [row for row in report["cases"] if row["case_id"] in FOCUS]
    report["comparison_limit"] = "固定合成数据和人工标签；Keyword 冻结报告无查询耗时；模型加载与建索引不计入单次查询耗时"
    return report


def markdown_report(report):
    model = report["model"]
    lines = ["# ShopPilot 第十一课真实 Embedding 评测", "", f'模型：`{model["name"]}`；版本：`{model["revision"] or "unknown"}`；sentence-transformers `{model["sentence_transformers_version"]}`；向量维度 {model["dimensions"]}；设备 `{model["device"]}`。', "", f'商品 {report["sample_size"]["products"]} 件，查询 {report["sample_size"]["queries"]} 条，均为合成测试数据；K=3。', "", f'模型加载 {report["model_load_ms"]} ms；整次评测 {report["total_eval_ms"]} ms。Keyword 基线耗时未测。', "", "| 方法 | Precision@3 | Recall@3 | Hit@3 | MRR | NDCG@3 | 硬约束满足率 | 平均查询 ms |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for method in METHODS:
        s = report["summary"][method]
        lines.append(f'| {method} | {s["precision_at_k"]} | {s["recall_at_k"]} | {s["hit_at_k"]} | {s["mrr"]} | {s["ndcg_at_k"]} | {s["hard_constraint_satisfaction_rate"]} | {s["mean_query_ms"]} |')
    lines += ["", "## 重点失败与标签争议", "", "c29 原始 Query 只有“便宜”和“最多看一页”，没有 200 元数值预算；原标签包含该预算。以下结果保留原标签，不作隐性修正。", ""]
    for row in report["focus_cases"]:
        lines.append(f'### {row["case_id"]}：{row["query"]}')
        lines.append(f'期望：{row["expected_product_ids"]}。')
        for method in METHODS:
            result = row["results"][method]
            lines.append(f'- {method}: {result["ids"]}；{row["failure_analysis"][method]}')
        lines.append("")
    lines += ["## 实验限制", "", report["comparison_limit"], "真实向量结果仅代表此模型在固定合成小样本上的表现；第七课 Mock 指标不是语义能力证据。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="显式运行真实 Embedding 评测；默认 pytest 不下载模型")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名或已下载的本地目录")
    parser.add_argument("--download", action="store_true", help="明确允许从模型源下载；不加则只读本地缓存")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "lesson11_real")
    args = parser.parse_args()
    products, cases = load_data()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    lesson06 = json.loads(LESSON06.read_text(encoding="utf-8"))
    started = perf_counter()
    embedder = RealSentenceTransformerEmbedder(args.model, allow_download=args.download)
    load_ms = round((perf_counter() - started) * 1000, 2)
    report = compare(products, cases, baseline, lesson06, embedder)
    report = enrich_report(report, products, cases, embedder, load_ms, round((perf_counter() - started) * 1000, 2))
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", args.model).strip("_")[-72:]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"retrieval_lesson11_{slug}_{timestamp}"
    json_path, md_path = args.output_dir / f"{stem}.json", args.output_dir / f"{stem}.md"
    with json_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    with md_path.open("x", encoding="utf-8") as output:
        output.write(markdown_report(report))
    print(json.dumps({"model": report["model"], "summary": report["summary"], "focus": {row["case_id"]: {name: row["results"][name]["ids"] for name in METHODS} for row in report["focus_cases"]}, "reports": [str(json_path), str(md_path)]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
