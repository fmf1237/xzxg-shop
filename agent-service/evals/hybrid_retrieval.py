"""关键词与向量候选按 RRF 融合，硬约束后做可解释的确定性重排。"""

from decimal import Decimal

from improved_retrieval import retrieve


def rrf(keyword_ids, vector_ids, constant=60):
    if constant <= 0:
        raise ValueError("RRF 常数必须为正数")
    scores = {}
    for ranking in (keyword_ids, vector_ids):
        for rank, product_id in enumerate(dict.fromkeys(ranking), 1):
            scores[product_id] = scores.get(product_id, 0.0) + 1 / (constant + rank)
    return sorted(scores, key=lambda product_id: (-scores[product_id], product_id)), scores


def _hard_reasons(product, parsed):
    reasons = []
    if parsed["brand"] and product["brand"] != parsed["brand"]:
        reasons.append("brand_mismatch")
    if parsed["category"] and product["category"] != parsed["category"]:
        reasons.append("category_mismatch")
    if parsed["max_price"] is not None and Decimal(product["price"]) > parsed["max_price"]:
        reasons.append("over_budget")
    return reasons


def hybrid_search(products, parsed, raw_query, index, k=3, candidate_k=None, rerank=False):
    if k < 1:
        raise ValueError("k 必须是正整数")
    candidate_k = candidate_k or len(products)
    trace = {"parsed_query": parsed, "keyword": [], "vector": [], "fusion": [], "filter": [], "rerank": [], "final_ids": [], "embedding_kind": index.embedder.kind}
    if any(code.startswith("conflicting_") or code == "invalid_budget" for code in parsed["diagnostics"]):
        trace["stop_reason"] = "conflicting_or_invalid_hard_constraint"
        return [], trace
    keyword_ids, _ = retrieve(products, parsed, k=candidate_k)
    vector_results = index.search(raw_query, k=candidate_k)
    vector_ids = [item["id"] for item in vector_results]
    trace["keyword"] = keyword_ids
    trace["vector"] = vector_results
    fused_ids, scores = rrf(keyword_ids, vector_ids)
    trace["fusion"] = [{"id": product_id, "rrf_score": scores[product_id]} for product_id in fused_ids]
    by_id = {product["id"]: product for product in products}
    eligible = []
    for product_id in fused_ids:
        product = by_id[product_id]
        reasons = _hard_reasons(product, parsed)
        trace["filter"].append({"id": product_id, "kept": not reasons, "reasons": reasons})
        if not reasons:
            eligible.append(product_id)
    if rerank:
        for product_id in eligible:
            product = by_id[product_id]
            searchable = " ".join([product["name"], product["category"], product["brand"], *product["selling_points"]]).casefold()
            soft_hits = [term for term in parsed["soft_requirements"] if term != "低价" and term.casefold() in searchable]
            query_hit = bool(parsed["keyword"] and parsed["keyword"].casefold() in searchable)
            cheap_bonus = 1 / (1 + float(Decimal(product["price"]))) if "低价" in parsed["soft_requirements"] else 0
            score = scores[product_id] + 0.02 * len(soft_hits) + 0.01 * query_hit + cheap_bonus
            trace["rerank"].append({"id": product_id, "score": score, "soft_hits": soft_hits, "keyword_hit": query_hit, "rrf_score": scores[product_id]})
        trace["rerank"].sort(key=lambda item: (-item["score"], item["id"]))
        eligible = [item["id"] for item in trace["rerank"]]
    trace["final_ids"] = eligible[:k]
    return trace["final_ids"], trace
