# Orders: MySQL + Redis 最小 CRUD 设计（FastAPI + Alembic）

## 背景与目标
在现有 `orders`（FastAPI + uv + make + `GET /healthz`）工程基础上，引入：
1. MySQL：用于持久化订单数据
2. Redis：用于缓存“按订单 id 查询”的订单详情
3. Alembic：用于提供可回滚的数据库迁移方案

本轮交付一个可用的“最小订单 CRUD”，并建立清晰的数据模型、迁移策略与缓存一致性规则。

## 非目标（Non-goals）
- 不引入鉴权/用户体系（`customer_name` 仅作为字符串字段出现）
- 不实现下单流程（payment/shipping 等），仅建模与基本状态流转
- 不提供列表接口（例如 `GET /orders`），避免范围膨胀
- 不在本轮引入消息队列/事件驱动等复杂基础设施

## MySQL 环境变量映射
迁移与运行时共用同一套配置：
- `MYSQL_HOST=127.0.0.1`
- `MYSQL_PORT=3306`
- `MYSQL_USER=root`
- `MYSQL_PASS=mysql1234`
- `MYSQL_DATABASE=superman`

构建连接串（示例）：`mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}`

## Redis 环境变量映射
- `REDIS_URL=redis://127.0.0.1:6379`

Redis 只用于缓存，允许短时不可用并回退到 MySQL。

## 数据模型设计（MySQL 表结构）
### 1) `orders`（订单头表）
字段建议如下（迁移脚本需确保默认值与约束一致）：
- `id`：BIGINT，主键，AUTO_INCREMENT
- `customer_name`：VARCHAR(255)，NOT NULL
- `status`：VARCHAR(32)，NOT NULL，默认 `created`
- `currency`：CHAR(3)，NOT NULL，默认 `CNY`
- `subtotal_amount`：DECIMAL(12,2)，NOT NULL，默认 `0.00`
- `tax_amount`：DECIMAL(12,2)，NOT NULL，默认 `0.00`
- `total_amount`：DECIMAL(12,2)，NOT NULL，默认 `0.00`
- `created_at`：TIMESTAMP(6)，NOT NULL，默认 CURRENT_TIMESTAMP(6)
- `updated_at`：TIMESTAMP(6)，NOT NULL，默认 CURRENT_TIMESTAMP(6)，并在更新时自动变化（ON UPDATE）

`status` 允许值域（API 与服务端校验一致）：
- `created`
- `paid`
- `fulfilled`
- `cancelled`

### 2) `order_items`（订单明细表）
字段建议如下：
- `id`：BIGINT，主键，AUTO_INCREMENT
- `order_id`：BIGINT，NOT NULL，外键引用 `orders(id)`，`ON DELETE CASCADE`
- `line_no`：INT，NOT NULL（同一订单内用于排序/稳定定位）
- `product_name`：VARCHAR(255)，NOT NULL
- `quantity`：INT，NOT NULL（> 0）
- `unit_price`：DECIMAL(12,2)，NOT NULL（>= 0）
- `line_total`：DECIMAL(12,2)，NOT NULL（由 `quantity * unit_price` 推导）

约束与索引：
- 唯一约束：`UNIQUE(order_id, line_no)`
- 索引：`INDEX(order_id)`

## Alembic 迁移方案（包含回滚）
使用 Alembic 管理迁移脚本，要求每个版本都提供可回滚的 `downgrade()`。

### migration 1：初始建表
- 创建 `orders` 表
- 创建 `order_items` 表
- 设置外键约束、唯一约束、索引
- `downgrade()`：按依赖顺序删除表（先 `order_items`，再 `orders`）

### 后续演进
- 若后续需要新增字段/索引，均通过新增迁移版本实现
- 禁止“手改表结构绕过迁移”以保证一致性

## Redis 缓存策略（按订单详情缓存）
### 缓存对象
缓存“订单详情”，包含：
- `orders` 头字段
- `order_items` 列表（`items[]`）

缓存 Key：
- `orders:by_id:{order_id}`

TTL：
- 建议 `60s`（短 TTL 降低长期脏读风险；配合写入失效策略进一步保证一致性）

### 读路径（Cache-Aside）
`GET /orders/{order_id}`：
1. `GET orders:by_id:{id}`
2. 命中：反序列化并直接返回
3. 未命中：
   - 查询 MySQL：`orders` + `order_items`
   - 组装与接口一致的响应结构
   - 写入 Redis（设置 TTL）
   - 返回

### 写路径（失效为主）
一致性规则：
- `POST /orders`：创建成功后写入新订单时可不需要删除（新 key 不存在）；但允许直接 set 新值或仅依赖未来读取
- `PATCH /orders/{id}`（仅更新 `status`）：
  - MySQL 更新成功后：`DEL orders:by_id:{id}`
- `DELETE /orders/{id}`：
  - MySQL 删除成功后：`DEL orders:by_id:{id}`

Redis 宕机/命令失败容错：
- API 不因 Redis 失败而失败：回退到 MySQL
- 失败需要可观测（日志记录），避免静默降级导致问题排查困难

## API 设计（最小 CRUD）
端点范围（本轮确认实现）：
1. `POST /orders`：创建订单（同时写 `orders` + `order_items`，单事务）
2. `GET /orders/{order_id}`：查询订单详情（Redis 缓存 aside）
3. `PATCH /orders/{order_id}`：仅更新订单 `status`
4. `DELETE /orders/{order_id}`：删除订单（级联删除 items）

### POST /orders
请求体（建议）：
- `customer_name`：string
- `currency`：string（可选，默认 `CNY`）
- `tax_amount`：decimal（可选，默认 `0.00`）
- `status`：string（可选；默认 `created`；如客户端不传则服务端设定）
- `items[]`：
  - `product_name`：string
  - `quantity`：int
  - `unit_price`：decimal

服务端计算：
- `line_total = quantity * unit_price`
- `subtotal_amount = sum(line_total)`
- `total_amount = subtotal_amount + tax_amount`
- `order_items.line_no`：按 items 顺序从 1..N 分配

事务：
- 单个事务写入 `orders` 与 `order_items`

响应：
- 返回与 `GET /orders/{id}` 相同的订单详情结构（含 items）

### GET /orders/{order_id}
响应结构：
- 订单头字段
- `items[]`

缓存：
- 命中直接返回
- 未命中走数据库组装并写入缓存（TTL）

### PATCH /orders/{order_id}
请求体：
- `status`：string（必须在允许集合 `created/paid/fulfilled/cancelled`）

处理：
- MySQL 更新成功后：`DEL orders:by_id:{id}`

响应：
- 返回更新后的订单详情（可选择：更新后从 DB 重新组装，或直接利用更新后的 status 组装，但必须与字段计算一致）

### DELETE /orders/{order_id}
处理：
- 删除 `orders` 行即可，items 通过外键 `ON DELETE CASCADE` 自动删除
- 删除成功后：`DEL orders:by_id:{id}`

响应：
- 最小响应：`204 No Content` 或 `{ "status": "deleted" }`（后续实现时二选一即可）

## 错误处理与状态码
- `400`：输入校验失败（status 不在允许集合、items 为空、数量/价格非法等）
- `404`：订单不存在
- `500`：数据库异常、Redis 失败（Redis 失败不应导致 500；仅在回退 MySQL 也失败时才返回 500）

## 测试策略（真实环境，不 mock）
由于要求“测试使用真实环境，不要 mock”，建议测试以环境变量连接真实 MySQL 与 Redis。

测试前置步骤（在实现阶段定义具体做法）：
1. 确保 Redis 可连接；不可连则测试跳过或失败（建议提供清晰报错）
2. 使用 Alembic 在测试启动前执行 `upgrade head`，保证 schema 存在
3. 测试用例之间清理数据：
   - 可通过清理 orders/order_items 表数据来保证隔离

建议覆盖的集成测试用例：
- `POST /orders`：创建成功，返回结构正确，MySQL 中 orders 与 order_items 行数正确
- `GET /orders/{id}`：首次未命中缓存走 MySQL，第二次命中返回一致
- `PATCH /orders/{id}`：更新 status 后缓存失效；再次 GET 返回新 status
- `DELETE /orders/{id}`：删除后 GET 返回 404，且缓存 key 被删除

## 实现与代码组织建议（与当前工程架构兼容）
- 配置：`src/orders/core/settings.py` 扩展 MySQL/Redis 相关字段，并提供连接配置构建方法
- 数据层：新增 `src/orders/core/db/*`（engine/session）、`src/orders/core/models/*`（SQLAlchemy models）
- 迁移：新增 `alembic/` 与 `alembic.ini`（具体以实现计划落地为准）
- 缓存层：新增 `src/orders/core/cache/*`（key 生成、get/set/del）
- API 层：新增 `src/orders/api/orders.py`（或直接扩展现有路由组织）
- 入口：沿用 `src/orders/main.py` include router

## 交付验证（实现完成后）
- `make install && make lock && make sync`
- `make test`：集成测试通过
- `make lint && make format`
- 手动验证：
  - `GET /healthz` 保持可用
  - `POST /orders` / `GET` / `PATCH` / `DELETE` 按预期联动 MySQL 与 Redis

