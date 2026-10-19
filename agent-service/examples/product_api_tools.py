"""通过 Go 的只读 HTTP API 查询商品；价格以字符串保留两位小数。"""

from decimal import Decimal, InvalidOperation
from functools import lru_cache
import os
from urllib.parse import quote

import requests


class ProductAPIError(Exception):
    """HTTP 状态、连接或格式错误；code 可供调用方区分。"""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ProductAPITools:
    def __init__(self, base_url=None, session=None, timeout=5, page_size=100, max_pages=20):
        self.base_url = (base_url or os.getenv("SHOP_API_BASE_URL", "")).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("请设置有效的 SHOP_API_BASE_URL")
        self.session = session or requests.Session()
        self.timeout = timeout
        if not 1 <= page_size <= 100 or max_pages < 1:
            raise ValueError("分页配置不合法")
        self.page_size = page_size
        self.max_pages = max_pages

    def _get(self, path, params=None):
        try:
            response = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
        except requests.Timeout as exc:
            raise ProductAPIError("timeout", "商品接口请求超时") from exc
        except requests.ConnectionError as exc:
            raise ProductAPIError("connection_error", "无法连接商品接口") from exc
        except requests.RequestException as exc:
            raise ProductAPIError("request_error", "商品接口请求失败") from exc
        if response.status_code >= 400:
            raise ProductAPIError(f"http_{response.status_code}", f"商品接口返回 HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProductAPIError("invalid_data", "商品接口返回非 JSON 数据") from exc

    @staticmethod
    def _normalise(item, detail=False):
        if not isinstance(item, dict):
            raise ProductAPIError("invalid_data", "商品数据不是对象")
        try:
            product_id, name, raw_price = item["productId"], item["name"], item["price"]
            if not isinstance(product_id, str) or not product_id or not isinstance(name, str) or not name or not isinstance(raw_price, str):
                raise ValueError("必填字段类型错误")
            price = Decimal(raw_price)
            if not price.is_finite() or price < 0:
                raise ValueError("价格不合法")
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise ProductAPIError("invalid_data", "商品缺少有效的 productId、name 或 price") from exc
        result = {"id": product_id, "name": name, "price": str(price)}
        for source, target in (("brand", "brand"), ("categoryId", "category"), ("stockStatus", "stock_status"), ("status", "status")):
            if source in item:
                if not isinstance(item[source], str):
                    raise ProductAPIError("invalid_data", f"商品字段 {source} 类型错误")
                result[target] = item[source]
        if detail:
            quantity = item.get("stockQuantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ProductAPIError("invalid_data", "商品详情缺少有效库存")
            result["stock_quantity"] = quantity
            if "description" in item:
                if not isinstance(item["description"], str):
                    raise ProductAPIError("invalid_data", "商品描述类型错误")
                result["description"] = item["description"]
        return result

    def search_products(self, keyword, max_price=None):
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("keyword 必须是非空字符串")
        if max_price is not None and (isinstance(max_price, bool) or not isinstance(max_price, int) or max_price <= 0):
            raise ValueError("max_price 必须是正整数")
        budget = Decimal(max_price) if max_price is not None else None
        matches = []
        for page in range(1, self.max_pages + 1):
            payload = self._get("/api/v1/products", {"keyword": keyword.strip(), "page": page, "page_size": self.page_size})
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or type(payload.get("total")) is not int or payload["total"] < 0 or payload.get("page") != page or payload.get("page_size") != self.page_size:
                raise ProductAPIError("invalid_data", "商品分页格式异常")
            total = payload["total"]
            if total > self.max_pages * self.page_size:
                raise ProductAPIError("pagination_limit", "商品结果超过安全分页范围，需缩小关键词")
            items = payload["items"]
            if len(items) > self.page_size or (page - 1) * self.page_size + len(items) > total:
                raise ProductAPIError("invalid_data", "商品分页数量与 total 不一致")
            if not items and (page - 1) * self.page_size < total:
                raise ProductAPIError("invalid_data", "商品分页提前结束")
            for item in items:
                product = self._normalise(item)
                if budget is None or Decimal(product["price"]) <= budget:
                    matches.append(product)
            if page * self.page_size >= total:
                return matches
        raise ProductAPIError("pagination_limit", "商品分页达到安全上限")

    def get_product_detail(self, product_id):
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id 必须是非空字符串")
        safe_id = quote(product_id.strip(), safe="")
        try:
            payload = self._get(f"/api/v1/products/{safe_id}")
        except ProductAPIError as exc:
            # Go API 对不存在的商品返回 404；该路由的 404 视为无详情。
            if exc.code == "http_404":
                return None
            raise
        product = self._normalise(payload, detail=True)
        if product["id"] != product_id.strip():
            raise ProductAPIError("invalid_data", "商品详情 ID 与请求不符")
        return product


@lru_cache(maxsize=1)
def _default_tools():
    return ProductAPITools()


def search_products(keyword, max_price=None):
    return _default_tools().search_products(keyword, max_price)


def get_product_detail(product_id):
    return _default_tools().get_product_detail(product_id)
