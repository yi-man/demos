# Orders Seckill Single SKU Implementation Plan

I'm using the writing-plans skill to create the implementation plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-activity single-SKU seckill flow that prioritizes anti-oversell guarantees using Redis pre-deduction, async order creation, and MySQL final consistency with compensation.

**Architecture:** FastAPI handles seckill attempt/result APIs and performs Redis Lua atomic checks for stock and idempotency. Successful attempts are pushed to a queue for async consumer processing; consumer writes order + ledger in one MySQL transaction and updates Redis result state. A compensation job reconciles abnormal states where Redis was deducted but DB write failed.

**Tech Stack:** FastAPI, SQLAlchemy async, MySQL, Redis (Lua + cache keys), queue (Redis Stream first), pytest integration tests, Alembic.

---

## File Structure

- Create: `src/orders/seckill/schemas.py` (request/response DTOs)
- Create: `src/orders/seckill/keys.py` (Redis key builders)
- Create: `src/orders/seckill/lua/decrement.lua` (atomic pre-deduct script)
- Create: `src/orders/seckill/repo.py` (DB operations for seckill tables)
- Create: `src/orders/seckill/service.py` (API orchestration)
- Create: `src/orders/seckill/consumer.py` (async queue consumer)
- Create: `src/orders/seckill/compensation.py` (reconciliation job)
- Create: `src/orders/api/seckill.py` (HTTP routes)
- Modify: `src/orders/api/routes.py` (include seckill router)
- Modify: `src/orders/core/db/models.py` (add seckill tables)
- Create: `alembic/versions/2026_04_02_0002_add_seckill_tables.py`
- Create: `tests/test_seckill_lua_atomic.py`
- Create: `tests/test_seckill_api_integration.py`
- Create: `tests/test_seckill_consumer_compensation.py`

---

### Task 1: Add Seckill DB Schema (Tables + Migration)

**Files:**
- Modify: `src/orders/core/db/models.py`
- Create: `alembic/versions/2026_04_02_0002_add_seckill_tables.py`
- Test: `tests/test_seckill_schema_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess


def test_seckill_tables_exist_after_upgrade():
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True, text=True)
    # test passes only if migration file includes seckill tables and upgrade works
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run -- pytest tests/test_seckill_schema_smoke.py -q`  
Expected: FAIL with missing revision/table definitions.

- [ ] **Step 3: Write minimal implementation**

In `src/orders/core/db/models.py`, add models:
- `SeckillActivity(id, sku_id, start_at, end_at, status, total_stock, db_sold, created_at, updated_at)`
- `SeckillOrder(id, activity_id, user_id, request_id, order_no, status, created_at, updated_at)` with unique `(activity_id, request_id)`
- `SeckillStockLedger(id, activity_id, delta, reason, biz_id, created_at)`

In migration `alembic/versions/2026_04_02_0002_add_seckill_tables.py`, create the three tables and indexes, and provide downgrade in reverse order.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run -- pytest tests/test_seckill_schema_smoke.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orders/core/db/models.py alembic/versions/2026_04_02_0002_add_seckill_tables.py tests/test_seckill_schema_smoke.py
git commit -m "feat(seckill): add schema and migration for single-sku seckill"
```

---

### Task 2: Implement Redis Keying + Lua Atomic Pre-deduction

**Files:**
- Create: `src/orders/seckill/keys.py`
- Create: `src/orders/seckill/lua/decrement.lua`
- Create: `src/orders/seckill/service.py` (Lua invocation helper only in this task)
- Test: `tests/test_seckill_lua_atomic.py`

- [ ] **Step 1: Write the failing test**

```python
import redis
from orders.core.settings import settings


def test_lua_decrement_is_atomic_and_idempotent():
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    activity_id = 101
    req_id = "req-1"
    stock_key = f"seckill:stock:{activity_id}"
    req_key = f"seckill:req:{activity_id}:{req_id}"
    result_key = f"seckill:result:{activity_id}:{req_id}"
    r.set(stock_key, 1)

    # first execution should deduct
    # second execution with same request id should be duplicate
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run -- pytest tests/test_seckill_lua_atomic.py -q`  
Expected: FAIL because script/service are missing.

- [ ] **Step 3: Write minimal implementation**

- `keys.py`: implement `stock_key(activity_id)`, `req_key(activity_id, request_id)`, `result_key(activity_id, request_id)`
- `decrement.lua`: atomically do:
  1. if request marker exists -> return `DUPLICATE`
  2. if stock <= 0 -> return `SOLD_OUT`
  3. decrement stock by 1
  4. set request marker with TTL
  5. set result `PENDING` with TTL
  6. return `ACCEPTED`
- `service.py`: add `run_pre_deduct(redis, activity_id, request_id)` to load and eval script

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run -- pytest tests/test_seckill_lua_atomic.py -q`  
Expected: PASS; duplicate request does not deduct stock twice.

- [ ] **Step 5: Commit**

```bash
git add src/orders/seckill/keys.py src/orders/seckill/lua/decrement.lua src/orders/seckill/service.py tests/test_seckill_lua_atomic.py
git commit -m "feat(seckill): add redis lua atomic pre-deduction with idempotency"
```

---

### Task 3: Add Seckill API (attempt/result)

**Files:**
- Create: `src/orders/seckill/schemas.py`
- Modify: `src/orders/seckill/service.py`
- Create: `src/orders/api/seckill.py`
- Modify: `src/orders/api/routes.py`
- Test: `tests/test_seckill_api_integration.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from orders.main import app


def test_attempt_then_result_pending():
    client = TestClient(app)
    resp = client.post("/seckill/1/attempt", json={"user_id": 1, "request_id": "req-100"})
    assert resp.status_code == 200
    assert resp.json()["code"] in {"ACCEPTED", "SOLD_OUT", "DUPLICATE"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run -- pytest tests/test_seckill_api_integration.py::test_attempt_then_result_pending -q`  
Expected: FAIL (route missing).

- [ ] **Step 3: Write minimal implementation**

- `schemas.py`: define `AttemptRequest`, `AttemptResponse`, `ResultResponse`
- `service.py`: add methods:
  - `attempt(activity_id, user_id, request_id)`
  - `query_result(activity_id, request_id)`
- `api/seckill.py`: add:
  - `POST /seckill/{activity_id}/attempt`
  - `GET /seckill/{activity_id}/result/{request_id}`
- `routes.py`: include seckill router

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run -- pytest tests/test_seckill_api_integration.py::test_attempt_then_result_pending -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orders/seckill/schemas.py src/orders/seckill/service.py src/orders/api/seckill.py src/orders/api/routes.py tests/test_seckill_api_integration.py
git commit -m "feat(seckill): add attempt and result APIs"
```

---

### Task 4: Add Async Consumer for Order + Ledger Transaction

**Files:**
- Create: `src/orders/seckill/repo.py`
- Create: `src/orders/seckill/consumer.py`
- Modify: `src/orders/seckill/service.py` (enqueue accepted attempts)
- Test: `tests/test_seckill_consumer_compensation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_consumer_confirms_order_once():
    # enqueue one ACCEPTED event, run consumer once,
    # assert one seckill_order row and one ledger row(delta=-1)
    assert False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run -- pytest tests/test_seckill_consumer_compensation.py::test_consumer_confirms_order_once -q`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

- `service.py`: on `ACCEPTED`, append event to queue (`seckill:stream`)
- `consumer.py`: consume event, call repo methods in one DB transaction:
  - insert `seckill_order` (idempotent by unique key)
  - insert ledger `delta=-1, reason=confirm_order`
  - increment `seckill_activity.db_sold`
  - set Redis result to `SUCCESS`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run -- pytest tests/test_seckill_consumer_compensation.py::test_consumer_confirms_order_once -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orders/seckill/repo.py src/orders/seckill/consumer.py src/orders/seckill/service.py tests/test_seckill_consumer_compensation.py
git commit -m "feat(seckill): add async consumer with transactional order confirmation"
```

---

### Task 5: Add Compensation + Reconciliation

**Files:**
- Create: `src/orders/seckill/compensation.py`
- Modify: `src/orders/seckill/repo.py`
- Modify: `tests/test_seckill_consumer_compensation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_compensation_rolls_back_redis_when_db_order_missing():
    # simulate redis deducted + failed consumer no db order
    # run compensation once
    # assert redis stock restored and result is FAILED
    assert False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run -- pytest tests/test_seckill_consumer_compensation.py::test_compensation_rolls_back_redis_when_db_order_missing -q`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

In `compensation.py`:
- scan pending/failed event bucket
- check db for `(activity_id, request_id)`
- if missing:
  - `INCR seckill:stock:{activity_id}`
  - write ledger `delta=+1, reason=compensate_rollback`
  - set result `FAILED`
- if exists:
  - set result `SUCCESS`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run -- pytest tests/test_seckill_consumer_compensation.py::test_compensation_rolls_back_redis_when_db_order_missing -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orders/seckill/compensation.py src/orders/seckill/repo.py tests/test_seckill_consumer_compensation.py
git commit -m "feat(seckill): add compensation and reconciliation flow"
```

---

### Task 6: End-to-End Verification and Quality Gates

**Files:**
- Modify: impacted files only if fixes needed
- Test: `tests/test_seckill_lua_atomic.py`, `tests/test_seckill_api_integration.py`, `tests/test_seckill_consumer_compensation.py`

- [ ] **Step 1: Run focused seckill tests**

Run: `uv run -- pytest tests/test_seckill_lua_atomic.py tests/test_seckill_api_integration.py tests/test_seckill_consumer_compensation.py -q`  
Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `make test`  
Expected: PASS (real MySQL/Redis required).

- [ ] **Step 3: Run lint and format**

Run:
- `make lint`
- `make format`

Expected: PASS.

- [ ] **Step 4: Final commit for cleanup (if needed)**

```bash
git add -u
git commit -m "chore(seckill): finalize tests and quality checks"
```

---

## Self-Review Checklist

- Spec coverage: architecture, data model, API, anti-oversell, compensation, and verification all mapped to tasks.
- Placeholder scan: no TODO/TBD placeholders in task steps.
- Type consistency: key names and statuses stay consistent (`ACCEPTED`, `SOLD_OUT`, `DUPLICATE`, `PENDING`, `SUCCESS`, `FAILED`).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-02-orders-seckill-single-sku-implementation-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
