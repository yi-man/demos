# Orders 秒杀场景设计（单活动单 SKU，防超卖优先）

## 1. 背景与目标

在现有 `orders` 项目（FastAPI + MySQL + Redis）基础上，新增一个最小可用的秒杀能力，优先目标是高并发下不超卖。

本设计已确认约束：
- 一致性目标：B（理论 0 超卖，极端异常允许补偿收敛）
- 扣减策略：C（Redis 预扣 + MySQL 最终校验双保险）
- 本期不做限购（不做每人 1 件或自定义件数）
- 商品范围：单活动、单商品（单 SKU）

## 2. 非目标（Non-goals）

- 不实现多活动多 SKU 平台化能力
- 不实现用户风控体系（设备指纹、黑白名单、行为打分）
- 不实现支付链路（仅到秒杀订单确认阶段）
- 不在本期引入复杂运营系统（如活动编排后台）

## 3. 总体架构

核心原则：
- Redis 承担高并发入口闸门
- MySQL 承担最终业务事实
- 补偿任务承担极端异常修复

组件划分：
1. Seckill API（FastAPI）
   - 入站请求校验（活动时间、参数完整性、幂等键）
   - 调用 Redis Lua 脚本做原子预扣
   - 成功后投递消息，快速返回排队中
2. Redis（库存闸门 + 状态缓存）
   - 原子扣减库存，避免并发读写竞争
   - 记录请求幂等痕迹与抢购结果
3. 消息队列（异步削峰）
   - 缓冲高峰流量，避免 MySQL 被同步写打爆
4. Consumer（异步下单）
   - 事务内落 MySQL 订单与库存流水
   - 更新抢购结果状态（成功/失败）
5. MySQL（最终事实）
   - 秒杀订单与库存流水的唯一可信账本
6. 补偿与对账任务
   - 修复“Redis 已扣但 DB 未成功落单”等异常窗口

## 4. 数据模型

### 4.1 MySQL 表设计

#### `seckill_activity`
- `id` BIGINT PK
- `sku_id` BIGINT NOT NULL
- `start_at` DATETIME(6) NOT NULL
- `end_at` DATETIME(6) NOT NULL
- `status` VARCHAR(32) NOT NULL（`pending`/`online`/`closed`）
- `total_stock` INT NOT NULL
- `db_sold` INT NOT NULL DEFAULT 0
- `created_at` DATETIME(6) NOT NULL
- `updated_at` DATETIME(6) NOT NULL

约束：
- `total_stock >= 0`
- `db_sold >= 0`
- `start_at < end_at`

#### `seckill_order`
- `id` BIGINT PK
- `activity_id` BIGINT NOT NULL
- `user_id` BIGINT NOT NULL
- `request_id` VARCHAR(64) NOT NULL
- `order_no` VARCHAR(64) NOT NULL
- `status` VARCHAR(32) NOT NULL（`pending`/`confirmed`/`cancelled`）
- `created_at` DATETIME(6) NOT NULL
- `updated_at` DATETIME(6) NOT NULL

约束与索引：
- UNIQUE(`activity_id`, `request_id`)：请求级幂等
- UNIQUE(`order_no`)
- INDEX(`activity_id`, `user_id`)

#### `seckill_stock_ledger`
- `id` BIGINT PK
- `activity_id` BIGINT NOT NULL
- `delta` INT NOT NULL（-1 扣减，+1 回补）
- `reason` VARCHAR(64) NOT NULL（`confirm_order`/`compensate_rollback`）
- `biz_id` VARCHAR(64) NOT NULL（订单号或补偿任务号）
- `created_at` DATETIME(6) NOT NULL

约束与索引：
- INDEX(`activity_id`, `created_at`)
- INDEX(`biz_id`)

### 4.2 Redis Key 设计

- `seckill:stock:{activity_id}`
  - 类型：string（整数）
  - 含义：当前可抢库存
- `seckill:req:{activity_id}:{request_id}`
  - 类型：string
  - 含义：请求幂等痕迹（防重复扣）
- `seckill:result:{activity_id}:{request_id}`
  - 类型：json/string
  - 含义：抢购结果（`PENDING` / `SUCCESS` / `FAILED`）

## 5. 核心流程与状态流转

### 5.1 抢购入口流程

`POST /seckill/{activity_id}/attempt`
1. API 校验活动是否开始、是否结束
2. 执行 Lua 脚本（同一原子单元内）
   - 判断 `request_id` 是否已处理
   - 判断库存是否 `> 0`
   - 库存 `-1`
   - 标记请求已处理
   - 写入结果初始态 `PENDING`
3. Lua 失败则直接返回 `SOLD_OUT` 或 `DUPLICATE`
4. Lua 成功则投递异步消息并返回 `ACCEPTED`

### 5.2 异步下单流程

Consumer 消费成功扣减消息后：
1. 开启 MySQL 事务
2. 写 `seckill_order`（`status=confirmed`）
3. 写 `seckill_stock_ledger`（`delta=-1`）
4. 更新 `seckill_activity.db_sold = db_sold + 1`
5. 事务提交后更新 Redis 结果为 `SUCCESS + order_no`

### 5.3 异常与补偿流程

适用场景：Redis 已扣但消费者多次失败，未形成有效订单。

处理步骤：
1. 标记消息为异常待补偿
2. 补偿任务扫描并核对 DB 是否已有对应 `request_id` 订单
3. 若无订单：
   - Redis 库存回补 `+1`
   - 写 `seckill_stock_ledger`（`delta=+1`, `reason=compensate_rollback`）
   - 结果状态标记 `FAILED`
4. 若已有订单：补写结果状态为 `SUCCESS`

## 6. API 设计

### 6.1 `POST /seckill/{activity_id}/attempt`

请求：
- `user_id`: int
- `request_id`: string（客户端生成，全局唯一）

返回（业务码）：
- `ACCEPTED`：进入异步队列，结果待确认
- `SOLD_OUT`：库存不足
- `DUPLICATE`：重复请求，返回已存在状态

HTTP 建议：
- 参数错误：`400`
- 活动状态冲突（未开始/已结束）：`409`
- 业务失败（售罄/重复）：`200` + 业务码

### 6.2 `GET /seckill/{activity_id}/result/{request_id}`

返回：
- `PENDING`
- `SUCCESS` + `order_no`
- `FAILED` + `reason`

### 6.3 `GET /seckill/{activity_id}/stock`（可选）

返回：
- Redis 可用库存
- DB 已售数量（`db_sold`）

说明：此接口仅用于观测和压测辅助，不作为下单可信判定源。

## 7. 防超卖机制（硬约束）

1. Redis Lua 原子扣减：杜绝并发读写竞态
2. 双端幂等：
   - API 入口幂等（`request_id`）
   - Consumer 落库幂等（MySQL 唯一约束）
3. 事务一致性：订单与库存流水必须同事务提交
4. 异常补偿：失败消息进入补偿闭环
5. 定时对账：持续检测 Redis 与 DB 偏差并告警

## 8. 测试与验收标准（真实环境，无 mock）

### 8.1 并发正确性
- 压测请求数 `N` 远大于库存 `S` 时，最终成功订单数 `<= S`
- 不出现负库存

### 8.2 幂等正确性
- 同一 `request_id` 重放多次最多成功 1 单
- 重复查询结果稳定一致

### 8.3 一致性正确性
- `db_sold` 与库存流水净变化一致
- Redis 与 DB 差异在补偿后收敛

### 8.4 故障恢复能力
- Consumer 重启后可继续消费且不重复扣减
- Redis 或队列短时故障后，系统不产生脏账

### 8.5 可观测性
- 指标至少覆盖：
  - 扣减成功率
  - 售罄率
  - 消费堆积长度
  - 补偿触发次数
  - 对账差异数量
- 日志可按 `activity_id`、`request_id`、`order_no` 关联追踪

## 9. 里程碑建议（实现顺序）

1. 建表与迁移：`seckill_activity` / `seckill_order` / `seckill_stock_ledger`
2. Redis Lua 脚本 + API attempt/result
3. 消息队列与 Consumer 事务落库
4. 补偿任务与对账任务
5. 压测与故障演练

## 10. 风险与边界说明

- Redis 与 MySQL 不会天然强一致，因此必须依赖补偿和对账
- 在极端网络分区下，可能出现短暂“已扣未单”窗口，但需保证最终收敛
- 当前不做限购，若未来加入限购需扩展用户维度幂等与计数模型

