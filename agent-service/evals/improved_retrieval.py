"""先执行硬约束，再按软需求排序的离线商品检索。"""

from decimal import Decimal


def retrieve(products, parsed, k=3):
    if k < 1:
        raise ValueError("k 必须是正整数")
    trace = {"parsed_query": parsed, "candidates": [], "filtered": [], "ranking": [], "final_ids": []}
    if any(code.startswith("conflicting_") or code == "invalid_budget" for code in parsed["diagnostics"]):
        trace["stop_reason"] = "conflicting_or_invalid_hard_constraint"
        return [], trace

    keyword = (parsed["keyword"] or "").casefold()
    soft = parsed["soft_requirements"]
    for product in products:
        searchable = " ".join([product["name"], product["category"], product["brand"], *product["selling_points"]]).casefold()
        soft_hits = [term for term in soft if term != "低价" and term.casefold() in searchable]
        if keyword and keyword not in searchable:
            continue
        if not keyword and not parsed["category"] and not parsed["brand"] and not soft:
            continue
        trace["candidates"].append(product["id"])
        reasons = []
        if parsed["category"] and product["category"] != parsed["category"]:
            reasons.append("category_mismatch")
        if parsed["brand"] and product["brand"] != parsed["brand"]:
            reasons.append("brand_mismatch")
        if parsed["max_price"] is not None and Decimal(product["price"]) > parsed["max_price"]:
            reasons.append("over_budget")
        if reasons:
            trace["filtered"].append({"id": product["id"], "reasons": reasons})
            continue
        trace["ranking"].append({"id": product["id"], "soft_hits": soft_hits, "score": len(soft_hits), "price": product["price"]})

    # 软需求只改变排序；已满足硬约束的候选不会因没有软命中而被删掉。
    cheap = "低价" in soft
    trace["ranking"].sort(key=lambda item: (-item["score"], Decimal(item["price"]) if cheap else Decimal(0), item["id"]))
    trace["final_ids"] = [item["id"] for item in trace["ranking"][:k]]
    return trace["final_ids"], trace
