# FastAPI 工程初始化（`uv` + `make` + 模块 `orders`） Implementation Plan

I'm using the writing-plans skill to create the implementation plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从空目录初始化一个可复现的 FastAPI 服务工程，提供 `uv` 依赖/虚拟环境管理与一组标准 `make` 命令（含 `/healthz` 健康检查与最小测试/质量门槛）。

**Architecture:** 采用 `src/` 布局，应用入口在 `src/orders/main.py`，路由拆分到 `src/orders/api/*`，配置通过 `src/orders/core/settings.py` 提供。`make` 目标对齐 spec 的依赖顺序：`python -> lock -> sync -> dev/run/test/lint/format`，并固定 `uv.lock` + `sync --frozen` 确保可复现。

**Tech Stack:** `uv`（含 `uv.lock`）、FastAPI、Uvicorn、`pydantic-settings`、`pytest`、`ruff`、`setuptools`/`build`。

---

## Task 1: Scaffold 项目元信息与工具配置

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `README.md`
- Create: `.gitignore`
- Create: `src/orders/__init__.py`
- Create: `src/orders/api/__init__.py`
- Create: `src/orders/core/__init__.py`

- [ ] **Step 1: Write project metadata/tooling files**

Create `pyproject.toml` with the following content:

```toml
[build-system]
requires = ["setuptools>=69.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "orders"
version = "0.1.0"
description = "Orders FastAPI service"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.110.0",
  "uvicorn[standard]>=0.27.0",
  "pydantic-settings>=2.0.0"
]
optional-dependencies = { dev = [
  "pytest>=8.0.0",
  "ruff>=0.6.0",
  "build>=1.2.0"
] }

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

```

Create `Makefile` with the following content:

```makefile
SHELL := /bin/bash

MODULE := orders
PYTHON_VERSION := 3.13
HOST ?= 127.0.0.1
PORT ?= 9600

.PHONY: python lock sync dev run test lint format build docs

python:
	uv python install $(PYTHON_VERSION)

lock:
	uv lock --python $(PYTHON_VERSION)

sync: lock
	uv sync --python $(PYTHON_VERSION) --frozen

dev: sync
	uv run -- uvicorn --reload --host $(HOST) --port $(PORT) $(MODULE).main:app

run: sync
	uv run -- uvicorn --host $(HOST) --port $(PORT) $(MODULE).main:app

test: sync
	uv run -- pytest

lint: sync
	uv run -- ruff check .

format: sync
	uv run -- ruff format .

build: sync
	uv run -- python -m build

docs:
	@python - <<'PY'
import pathlib

readme = pathlib.Path("README.md")
readme.write_text(
    "# Orders (FastAPI)\\n\\n"
    "Quickstart\\n\\n"
    "## Setup\\n"
    "- `make python`\\n"
    "- `make lock`\\n"
    "- `make sync`\\n\\n"
    "## Run\\n"
    "- Dev (hot reload): `make dev`\\n"
    "- Prod-like: `make run`\\n\\n"
    "Health check\\n\\n"
    "- `curl http://127.0.0.1:9600/healthz`\\n"
    "\\n"
)
print("README.md updated.")
PY

```

Create `.gitignore` with the following content:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/

dist/
build/
*.egg-info/

# uv lock should be committed for reproducibility, so do not ignore uv.lock.
```

Create `README.md` with a minimal placeholder (it will be overwritten by `make docs`):

```md
# Orders (FastAPI)

Run `make docs` to generate the README quickstart.
```

Create these empty package init files:

`src/orders/__init__.py`
```python
```

`src/orders/api/__init__.py`
```python
```

`src/orders/core/__init__.py`
```python
```

- [ ] **Step 2: Run formatting/lint sanity checks**

Run:

```bash
make lint
```

Expected:
- Command exits successfully.

- [ ] **Step 3: Minimal implementation**

No additional code for this task beyond scaffolding.

- [ ] **Step 4: Run tests (should be empty or pass)**

Run:

```bash
make test
```

Expected:
- If no tests exist yet, pytest exits successfully or with no tests collected.

- [ ] **Step 5: Commit**

Run:

```bash
git add pyproject.toml Makefile README.md .gitignore src/orders/__init__.py src/orders/api/__init__.py src/orders/core/__init__.py
git commit -m "feat: scaffold uv+make FastAPI orders project"
```

---

## Task 2: Add failing health endpoint test

**Files:**
- Create: `tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from orders.main import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
make test
```

Expected:
- FAIL due to missing `orders.main` and/or missing `/healthz` route.

- [ ] **Step 3: Write minimal implementation**

No implementation in this task; implementation comes in Task 3.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
make test
```

Expected:
- Still FAIL (this step is intentionally redundant to preserve the TDD structure).

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/test_health.py
git commit -m "test: add healthz test for orders service"
```

---

## Task 3: Implement FastAPI app entry + `/healthz`

**Files:**
- Create: `src/orders/main.py`
- Create: `src/orders/api/health.py`
- Create: `src/orders/api/routes.py`

- [ ] **Step 1: Write minimal app and route to make the test pass**

Create `src/orders/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

Create `src/orders/api/routes.py`:

```python
from fastapi import APIRouter

from .health import router as health_router

router = APIRouter()
router.include_router(health_router)
```

Create `src/orders/main.py`:

```python
from fastapi import FastAPI

from orders.api.routes import router

app = FastAPI(title="Orders API")
app.include_router(router)
```

- [ ] **Step 2: Run test to verify it fails or passes appropriately**

Run:

```bash
make test
```

Expected:
- PASS.

- [ ] **Step 3: Add small guard for module import stability**

No extra code needed; `orders.main:app` import should be stable.

- [ ] **Step 4: Run lint check**

Run:

```bash
make lint
```

Expected:
- PASS (no ruff errors).

- [ ] **Step 5: Commit**

Run:

```bash
git add src/orders/main.py src/orders/api/health.py src/orders/api/routes.py
git commit -m "feat: implement FastAPI app and /healthz"
```

---

## Task 4: Add Settings module (env-based config channel)

**Files:**
- Create: `src/orders/core/settings.py`
- Modify: `src/orders/main.py` (to instantiate Settings and wire debug if desired)

- [ ] **Step 1: Write Settings implementation**

Create `src/orders/core/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 9600

    model_config = SettingsConfigDict(
        env_prefix="ORDERS_",
        extra="ignore",
    )


settings = Settings()
```

- [ ] **Step 2: Modify app to use Settings**

Update `src/orders/main.py` to:

```python
from fastapi import FastAPI

from orders.api.routes import router
from orders.core.settings import settings

app = FastAPI(title="Orders API", debug=settings.debug)
app.include_router(router)
```

- [ ] **Step 3: Run tests**

Run:

```bash
make test
```

Expected:
- PASS.

- [ ] **Step 4: Run format**

Run:

```bash
make format
```

Expected:
- Command exits successfully.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/orders/core/settings.py src/orders/main.py
git commit -m "feat: add env settings module for orders"
```

---

## Task 5: Ensure build target works and update docs/quickstart

**Files:**
- Modify: `README.md` (via `make docs`)

- [ ] **Step 1: Update README via `make docs`**

Run:

```bash
make docs
```

Expected:
- Prints `README.md updated.`

- [ ] **Step 2: Validate `make build` works**

Run:

```bash
make build
```

Expected:
- Command exits successfully and creates build artifacts under `dist/`.

- [ ] **Step 3: Final lint/format verification**

Run:

```bash
make lint
make format
make lint
```

Expected:
- Ruff check passes after formatting.

- [ ] **Step 4: Run dev health check manually (smoke)**

Run:

```bash
make dev
```

Expected:
- Uvicorn starts successfully.

In another terminal, run:

```bash
curl http://127.0.0.1:9600/healthz
```

Expected:
- Response JSON is `{"status":"ok"}`.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md
git commit -m "docs: add quickstart and verify build/dev targets"
```

---

## Task 6: Generate `uv.lock` and sync with frozen mode

**Files:**
- Create/Modify: `uv.lock`

- [ ] **Step 1: Generate lockfile**

Run:

```bash
make lock
```

Expected:
- `uv.lock` is created/updated.

- [ ] **Step 2: Sync environment from lockfile (frozen)**

Run:

```bash
make sync
```

Expected:
- Command exits successfully using `--frozen` (no lockfile updates).

- [ ] **Step 3: Re-run tests to confirm environment consistency**

Run:

```bash
make test
```

Expected:
- PASS.

- [ ] **Step 4: Commit lockfile**

Run:

```bash
git add uv.lock
git commit -m "chore: add uv.lock for reproducible orders dependencies"
```

---

## Task 7: Final repo verification

**Files:**
- Modify: none (verification only)

- [ ] **Step 1: One-shot make sanity suite**

Run:

```bash
make python
make lock
make sync
make lint
make format
make test
```

Expected:
- All commands exit successfully.

- [ ] **Step 2: Final smoke check endpoint**

Run:

```bash
make run
```

Expected:
- Uvicorn starts successfully.

In another terminal:

```bash
curl http://127.0.0.1:9600/healthz
```

Expected:
- Response JSON is `{"status":"ok"}`.

- [ ] **Step 3: Commit (if formatting changed files)**

If `make format` changed any tracked files, commit them:

```bash
git status --porcelain
git add -u
git commit -m "style: format with ruff"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-02-fastapi-uv-make-implementation-plan.md`.

Two execution options:
1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - Execute tasks in this session using `executing-plans` with checkpoints.

Which approach?

