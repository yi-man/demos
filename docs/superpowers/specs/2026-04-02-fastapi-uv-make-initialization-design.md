# FastAPI 工程初始化设计（`uv` + `make` + 模块 `orders`）

## 背景与目标
本项目从空目录开始创建一个可复现、可维护的 FastAPI 服务工程，并在工程层面建立统一的开发/测试/质量/运行入口：

1. 依赖管理使用 `uv`，通过 `uv.lock` 实现可复现安装。
2. 命令入口使用 `make`，将常用动作标准化为一组目标（targets）。
3. 项目代码结构使用 `src/` 布局，并以模块名 `orders` 组织应用入口与路由。
4. 默认提供健康检查接口 `GET /healthz`，便于本地与 CI 探测服务可用性。

## 非目标（Non-goals）
- 不实现业务领域功能（订单等业务逻辑仅预留扩展位置）。
- 不引入复杂基础设施（数据库、消息队列、鉴权、分布式追踪等）。
- 不在此轮引入 Docker/CI 管线（可在后续迭代添加）。

## 技术决策
### Python 与虚拟环境策略
- Python 版本：统一为 `3.13`。
- Python 自动安装：当本机缺少目标 Python 时，通过 `uv python install 3.13` 自动获取。
- 虚拟环境：使用项目级虚拟环境目录 `.venv/`。

### 依赖可复现策略（推荐：lockfile 驱动）
- 使用 `uv lock` 生成 `uv.lock`。
- 使用 `uv sync --frozen` 从 `uv.lock` 同步依赖到 `.venv/`。
- 要求所有运行/测试/质量命令在同一个虚拟环境内执行，并尽量确保以锁文件为准。

## make 命令体系设计
本设计按你前面确认的 target 列表命名，采用全小写短目标（例如 `make install` / `make sync` / `make dev` 等）：

### 基础目标
- `make install`
  - 作用：确保目标 Python `3.13` 存在。
  - 行为：`uv python install 3.13`（如已存在则跳过/快速返回）。

- `make lock`
  - 作用：生成或更新 `uv.lock`。
  - 行为：`uv lock`（依赖解析以 `pyproject.toml` 为准）。

- `make sync`
  - 作用：根据 `uv.lock` 同步到 `.venv/`，并冻结一致性。
  - 行为：`uv sync --frozen`
  - 约束：依赖锁文件缺失或不一致时，应让命令失败，提醒先执行 `make lock`。

### 开发/运行目标（依赖同步优先）
- `make dev`
  - 作用：以热重载启动本地开发服务器。
  - 依赖：`sync`
  - 行为：`uvicorn --reload --host 127.0.0.1 --port 9600 orders.main:app`

- `make run`
  - 作用：非热重载启动本地运行。
  - 依赖：`sync`
  - 行为：`uvicorn --host 127.0.0.1 --port 9600 orders.main:app`

### 质量与测试目标
- `make test`
  - 作用：运行测试。
  - 依赖：`sync`
  - 行为：`pytest`

- `make lint`
  - 作用：静态检查（不做变更）。
  - 依赖：`sync`
  - 行为：`ruff check .`

- `make format`
  - 作用：格式化代码。
  - 依赖：`sync`
  - 行为：`ruff format .`

### 构建/文档目标（轻量）
- `make build`
  - 作用：生成分发制品（如果采用标准 Python packaging）。
  - 依赖：`sync`
  - 行为：`python -m build`

- `make docs`
  - 作用：生成最小化工程文档（不强制引入 Sphinx）。
  - 依赖：无或仅依赖 `sync`（取决于实现方式）。
  - 行为：生成/更新 `README.md` 中的 Quickstart（包含 `make install/lock/sync/dev` 与 `GET /healthz` 调用方式）；不引入额外文档构建工具。

> 注：在实现阶段，会同步确认 target 是否采用 `uv run` 还是直接在 `.venv/bin/` 中执行。该设计只约束行为语义与依赖关系。

## FastAPI 基线结构设计
项目使用 `src/` 布局，并以模块名 `orders` 作为包名：

```
src/
  orders/
    __init__.py
    main.py
    api/
      __init__.py
      routes.py
      health.py
    core/
      __init__.py
      settings.py
tests/
  test_health.py
```

### 应用入口：`src/orders/main.py`
- 提供 `app = FastAPI(...)` 实例。
- 注册路由：从 `orders.api.routes` 引入 `router` 并 include 到 `app`。

### 路由组织：`src/orders/api/routes.py`
- 定义 `router = APIRouter()`
- 通过 include router 或直接 include 子路由，注册 `health`。

### 健康检查：`src/orders/api/health.py`
- 实现 `GET /healthz`
- 返回 JSON：`{"status": "ok"}`
- 健康检查不依赖外部资源（无数据库/无鉴权），仅用于连通性探测。

### 配置：`src/orders/core/settings.py`
- 使用环境变量配置，默认值兜底。
- `Settings` 的主要作用：为将来扩展（端口开关/开 debug/外部服务配置）提供通道。
- 本轮默认接口行为固定由代码保证（`/healthz`），但配置对象允许由环境变量覆盖以支持后续演进。

## 依赖清单（下一步实现时落地）
本设计目标依赖主要包括：
- `fastapi`
- `uvicorn[standard]`
- `pydantic-settings`（用于环境变量配置）
- `pytest`（测试框架）
- `ruff`（lint + format）
- `build`（用于 `make build`）

测试实现依赖：
- `fastapi.testclient.TestClient`（用于同步测试 `/healthz`）

## 测试策略
最小化测试覆盖：
- `tests/test_health.py`
  - 测试 `GET /healthz` 返回 HTTP 200
  - 测试响应 JSON 包含 `status == "ok"`

该测试用例是本轮 baseline 的验证点，确保服务启动与路由注册正常。

## 交付与验证（实现完成后执行的命令）
实现完成后，按以下验证路径确认可用性：
- `make install`
- `make lock`
- `make sync`
- `make test`
- `make lint`
- `make format`（可选：确认不再产生格式差异）
- `make dev` 并访问 `http://127.0.0.1:9600/healthz`

## 设计自检（占位符/一致性/范围）
- 无 `TBD` 关键需求占位符：目标端点 `/healthz` 与服务启动端口已明确。
- `uv.lock` 驱动与 `make sync --frozen` 一致，保证可复现安装路径。
- `make dev/run/test/lint/format` 依赖 `sync`，避免缺少依赖导致的运行失败。
- 本轮范围控制在工程骨架与最小验证，未引入复杂基础设施。

