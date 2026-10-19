"""规则式 Query Understanding：只把明确的品牌、类别、数字预算当硬约束。"""

import re


CATEGORY_ALIASES = {"跑鞋": "运动鞋", "球鞋": "运动鞋", "打字板": "键盘", "保湿霜": "面霜"}
SOFT_ALIASES = {"夏天": "夏季", "通勤": "通勤", "不吵": "静音", "安静": "静音", "便宜": "低价", "跑鞋": "跑步", "跑步": "跑步", "竞速": "跑步"}
STOP_WORDS = ("推荐", "帮我", "找", "一款", "一个", "的", "适合", "穿", "脸部", "电脑", "护肤", "设备", "打字", "但最多看一页")
BUDGET_PATTERNS = (
    r"预算\s*(\d+)\s*元?",
    r"不超过\s*(\d+)\s*元?",
    r"(\d+)\s*元\s*以内",
    r"最多\s*(\d+)\s*元",
)


def catalog_metadata(products):
    return {
        "brands": sorted({p["brand"] for p in products}, key=len, reverse=True),
        "categories": sorted({p["category"] for p in products}, key=len, reverse=True),
        "selling_points": sorted({point for p in products for point in p["selling_points"]}, key=len, reverse=True),
    }


def parse_query(query, metadata):
    if not isinstance(query, str) or not query.strip():
        return {"keyword": None, "category": None, "brand": None, "max_price": None, "soft_requirements": [], "diagnostics": ["empty_query"], "ambiguous": True}
    text = query.strip()
    diagnostics = []
    brands = [brand for brand in metadata["brands"] if brand in text]
    categories = [category for category in metadata["categories"] if category in text]
    aliases = [(alias, category) for alias, category in CATEGORY_ALIASES.items() if alias in text and category in metadata["categories"]]
    category_values = set(categories + [category for _, category in aliases])
    if len(brands) > 1:
        diagnostics.append("conflicting_brands")
    if len(category_values) > 1:
        diagnostics.append("conflicting_categories")
    prices = []
    for pattern in BUDGET_PATTERNS:
        prices.extend(int(value) for value in re.findall(pattern, text))
    if len(set(prices)) > 1:
        diagnostics.append("conflicting_budgets")
    if any(price <= 0 for price in prices):
        diagnostics.append("invalid_budget")
    if re.search(r"(?:预算|不超过)\s*[^\d\s]+\s*元", text):
        diagnostics.append("invalid_budget")

    soft = []
    for point in metadata["selling_points"]:
        if point in text and point not in soft:
            soft.append(point)
    for phrase, canonical in SOFT_ALIASES.items():
        if phrase in text and canonical not in soft:
            soft.append(canonical)
    if "跑步" in soft and "竞速" not in soft:
        soft.append("竞速")
    if "低价" in soft:
        diagnostics.append("qualitative_price_not_hard_limit")

    remainder = text
    for phrase in sorted(set(brands + categories + [alias for alias, _ in aliases] + list(SOFT_ALIASES) + metadata["selling_points"]), key=len, reverse=True):
        remainder = remainder.replace(phrase, "")
    for pattern in BUDGET_PATTERNS:
        remainder = re.sub(pattern, "", remainder)
    for word in STOP_WORDS:
        remainder = remainder.replace(word, "")
    remainder = re.sub(r"[\s，。！？、]+", "", remainder)
    if soft and not category_values and "鞋" in remainder and any(category.endswith("鞋") for category in metadata["categories"]):
        remainder = remainder.replace("鞋", "")
        diagnostics.append("generic_footwear_not_hard")
    keyword = remainder or None
    if not brands and not category_values and not soft and keyword:
        diagnostics.append("unrecognized_term")
    return {
        "keyword": keyword,
        "category": next(iter(category_values)) if len(category_values) == 1 else None,
        "brand": brands[0] if len(brands) == 1 else None,
        "max_price": prices[0] if prices and not any(d in diagnostics for d in ("conflicting_budgets", "invalid_budget")) else None,
        "soft_requirements": soft,
        "diagnostics": diagnostics,
        "ambiguous": any(d.startswith("conflicting_") or d in ("invalid_budget", "unrecognized_term") for d in diagnostics),
    }
