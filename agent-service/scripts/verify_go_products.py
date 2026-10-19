"""显式运行的只读 Go API 集成检查；不会在 pytest 中自动执行。"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from product_api_tools import ProductAPITools  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="检查已启动的 Go 商品 API")
    parser.add_argument("--base-url", required=True, help="例如 http://127.0.0.1:8080")
    args = parser.parse_args()
    tools = ProductAPITools(base_url=args.base_url)
    products = tools.search_products("Mouse")
    detail = tools.get_product_detail("p_mouse_001")
    if not any(item["id"] == "p_mouse_001" for item in products):
        raise SystemExit("搜索结果中没有 p_mouse_001")
    if detail is None or detail["id"] != "p_mouse_001":
        raise SystemExit("详情接口未返回 p_mouse_001")
    print({"search_count": len(products), "product": detail})


if __name__ == "__main__":
    main()
