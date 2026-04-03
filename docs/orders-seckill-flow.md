# 秒杀流程设计图（单活动单 SKU）

本文档描述当前工程内秒杀链路：**Redis Lua 预扣 → Redis Stream 异步落库 → MySQL 事务确认 → 可选补偿对账**。图中组件与 `src/orders/seckill/` 实现一致。

## 主流程（下单尝试与异步确认）

```mermaid
flowchart TB
    subgraph Client["客户端"]
        U[用户]
    end

    subgraph API["FastAPI"]
        ATT["POST /seckill/{activity_id}/attempt"]
        RES["GET /seckill/{activity_id}/result/{request_id}"]
    end

    subgraph Redis["Redis"]
        LUA["Lua 脚本（原子）"]
        SK["seckill:stock:{activity_id}"]
        REQ["seckill:req:{activity_id}:{request_id}"]
        OUT["seckill:result:{activity_id}:{request_id}"]
        STR["seckill:stream（XADD）"]
    end

    subgraph Consumer["异步消费者 consume_once"]
        READ["XREVRANGE 取最新一条"]
        TX["MySQL 单事务"]
    end

    subgraph DB["MySQL"]
        O["seckill_orders"]
        L["seckill_stock_ledgers delta=-1"]
        A["seckill_activities.db_sold += 1"]
    end

    U --> ATT
    ATT --> LUA
    LUA --> SK
    LUA --> REQ
    LUA --> OUT

    LUA -->|DUPLICATE| ATT
    LUA -->|SOLD_OUT| ATT
    LUA -->|ACCEPTED| STR
    STR --> ATT

    STR --> READ
    READ --> TX
    TX --> O
    TX --> L
    TX --> A
    TX --> OUT

    U --> RES
    RES --> OUT
```

**说明：**

- **Lua** 在一次原子执行内完成：幂等键、库存判断与扣减、结果初始态（如 `PENDING`）。
- **ACCEPTED** 后向 `seckill:stream` **XADD** 事件；消费者用 **XREVRANGE** 处理最新事件，避免重复消费历史残留。
- 消费者事务成功后 **SET** `seckill:result:*` 为 **SUCCESS**（与代码中 TTL 策略一致）。

## 补偿流程（Redis 已扣、DB 无单）

当异步落库失败或需人工/定时对账时，调用 **`reconcile_once`**（见 `src/orders/seckill/compensation.py`）：

```mermaid
flowchart TB
    START([reconcile_once]) --> Q{MySQL 是否存在<br/>该 request_id 订单?}

    Q -->|是| S[SET result = SUCCESS]
    S --> END1([结束])

    Q -->|否| LED[写入 ledger<br/>delta=+1, compensate_rollback]
    LED --> INC[INCR seckill:stock]
    INC --> F[SET result = FAILED]
    F --> END2([结束])
```

---

若需在 GitHub/GitLab 外预览 Mermaid，可使用支持 Mermaid 的 Markdown 预览或 [Mermaid Live Editor](https://mermaid.live)。
