# ShopPilot 第四课：通过 Go HTTP API 读取商品

## 实际接口契约

阅读 `backend/src/httpapi/server.go` 后确认：

| 用途 | 请求 | 响应 |
| --- | --- | --- |
| 商品列表 | `GET /api/v1/products?keyword=运动鞋&page=1&page_size=100`；另支持 `category_id` | `{"items": [ProductCard...], "page": 1, "page_size": 100, "total": 3}` |
| 商品详情 | `GET /api/v1/products/{product_id}` | 单个 `ProductDetail` 对象；不存在返回 HTTP 404，JSON 含 `code: product_not_found` |

`page` 默认 1，范围 1～100000；`page_size` 默认 10，范围 1～100。列表对象使用 `productId`、`name`、`price`、`stockStatus`、`status` 等驼峰字段。`price` 是字符串，例如 `"199.00"`；详情还含 `stockQuantity`、`description` 等。错误响应通常为 `{"code": "...", "message": "...", "request_id": "..."}`，HTTP 状态码体现失败类型。公开列表接口支持关键词和分类筛选，**不支持价格筛选**。

`backend/src/httpapi/server.go` 的 `handleListProducts` 调用 Store 接口 `ListProductsPage`；MySQL 实现位于 `backend/src/store/mysql.go`。其查询使用参数化的 `LIKE` 条件搜索名称、品牌、分类名、标签和卖点，按 `sort_order, product_id` 排序，以 `LIMIT ? OFFSET ?` 分页。公开列表只返回 active 商品且商家 active。`handleProductAction` 调用 `GetProduct` 按商品 ID 查询详情；该详情查询没有列表的 active 条件，调用方不应自行推断商品可售。Store 当前会把一些数据库读取错误折叠为无结果，因此 HTTP 200 的空列表未必能证明数据库绝对没有该商品；本课不修改 Go 逻辑。

## Python 工具的调用链

用户问题 → `run_react()` → FakeLLM 或 RealLLM 选择 `search_products` → [`product_api_tools.py`](../agent-service/examples/product_api_tools.py) → Go HTTP API → Store 接口 → MySQL `products` 表 → HTTP JSON → 标准化商品 → Observation → 下一轮模型。

工具通过现有注入入口接入，不改 Agent 循环：

```python
api = ProductAPITools()  # 从 SHOP_API_BASE_URL 读取地址
result = run_react(question, llm=llm, tools={
    "search_products": api.search_products,
    "get_product_detail": api.get_product_detail,
})
```

`ProductAPITools` 复用一个 `requests.Session`，每次请求设置超时。列表服务器端按关键词筛选，Python 读取全部匹配页后再用 `Decimal` 按预算过滤；每页最多 100 条，默认最多 20 页。若服务器报告超过 2000 条，返回 `pagination_limit` 错误，避免把不完整的部分结果说成完整结果。工具不对关键词做额外客户端筛选，遵循 Go 搜索的语义。

标准化结果包含 `id`、`name`、字符串 `price`，并保留可用的品牌、类别 ID、库存状态和商品状态；详情还含库存数量和描述。商品不存在时详情返回 `None`，搜索无匹配返回 `[]`。HTTP 500、超时、连接失败、格式错误分别抛出 `ProductAPIError`，进入 Agent 后成为错误 Observation。HTTP 404 的详情视为无结果。

## MySQL 基础

迁移文件 `backend/migrations/001_mysql_schema.sql` 的 `products` 表以 `product_id VARCHAR(64)` 为主键；主键唯一标识一行，Agent 查询详情用的正是这个 ID。价格为 `DECIMAL(10,2)`，库存数量为 `INT`，库存状态和商品状态为字符串。表还包含商家、名称、品牌、分类、图片、标签等字段，并在分类、商家和状态上建索引。

- **SQL 查询**：`SELECT` 读取行；`WHERE` 限定条件；`ORDER BY` 指定顺序；`LIMIT` 和 `OFFSET` 控制每页数量和位置。
- **索引**：帮助数据库快速找到符合条件的行，代价是占空间且写入时需要维护。
- **连接池**：复用数据库连接，避免每次请求都重新建立连接。Go Store 负责数据库连接管理；Python 只复用 HTTP 会话。
- **Repository Pattern**：业务代码依赖 Store 接口，而非直接写数据库调用。这里 `ListProductsPage`、`GetProduct` 是数据访问边界，MySQLStore 实现它们。

暂时保留 Go Store 层，能沿用原项目的商品可见性、筛选和分页规则。Python 通过 HTTP 访问已有业务 API，开发和权限边界更清楚；直接连接 MySQL 可能减少一次网络转发，但需要在 Python 中重复连接管理、查询和业务规则，也增加数据库凭据管理负担。本课不增加 SQL 或数据库写入能力。

## 测试与验证

安装本课唯一新增依赖：`python -m pip install -r agent-service/examples/requirements.txt`。在仓库根目录运行：

```bash
python -m pytest agent-service/examples/test_minimal_agent.py agent-service/examples/test_react_agent.py agent-service/examples/test_real_llm.py agent-service/examples/test_product_api_tools.py -q
```

离线测试使用 Mock HTTP，检查正常搜索、详情、预算、空结果、HTTP 404/500、超时、连接失败、格式异常和分页上限。示例 Trace：模型输出 `search_products(keyword="运动鞋")`；Mock HTTP 返回 `p_001`；Observation 为 `status="ok"`、`result=[{"id":"p_001",...}]`；下一轮模型看到该 ID 并请求 `get_product_detail(product_id="p_001")`；详情 Observation 回填后输出 Final。这个 Trace 验证了 Agent 与 HTTP 工具的接线，**不代表已经访问真实 MySQL**。

本机未配置 `SHOP_API_BASE_URL`，`127.0.0.1:8080` 没有运行中的 Go API，Docker Desktop 守护进程也不可连接，因此本课未完成真实 Go + MySQL 集成验证。需要环境可用后，对已有数据执行只读请求；不要为通过测试自动写入数据库。

## 五道面试题

1. **为什么预算要在 Python 过滤？** 公开列表 API 没有价格参数；Python 必须读完服务器关键词匹配的页，才能得到完整的预算结果。
2. **分页结果过多怎么办？** 设置安全页数上限；超出时明确报错或要求缩小关键词，不能把部分结果当完整答案。
3. **商品 ID 与主键有什么关系？** API 的 `productId` 对应 `products.product_id` 主键，用于唯一定位详情行。
4. **HTTP 404 与搜索空列表有什么不同？** 404 表示指定详情资源不存在；空列表表示列表查询没有匹配项，且接口请求本身成功。
5. **为什么 Agent 不直接生成 SQL？** 模型输出不可靠且可能绕过业务规则；经固定工具和 Go API 查询，可以控制参数、权限和可见性。
