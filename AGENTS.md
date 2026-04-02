### Project: orders

orders 是一个 FastAPI 服务工程（包含 `uv` 依赖管理、`make` 命令入口，以及默认 `GET /healthz` 健康检查）。

---

### 规范

- 遵循 PEP 8 风格，并使用 `ruff check .` 与 `ruff format .` 统一代码质量与格式（通过 `make lint` / `make format` 执行）
- 依赖管理使用 `uv`：以 `uv.lock` 为准，通过 `make lock` / `make sync --frozen` 同步到 `.venv`
- API/路由/返回值建议添加类型注解（便于可读性与后续静态分析）
- 代码分层遵循 `src/orders/core`（配置/核心）+ `src/orders/api`（路由）+ `src/orders/main.py`（应用入口）

---

### 常用命令

- `make install`: 安装并准备项目目标 Python 版本（当前为 3.13）
- `make lock`: 生成/更新 `uv.lock`（用于可复现依赖解析）
- `make sync`: 根据 `uv.lock` 同步虚拟环境（`--frozen`，避免锁被悄悄更新）
- `make dev`: 启动热重载开发服务器（默认 `127.0.0.1:9600`）
- `make test`: 运行测试（pytest）
- `make lint`: 代码检查（ruff check）
- `make format`: 代码格式化（ruff format）
- `make build`: 构建分发制品（python -m build）

---

### 项目架构

```
.
├── src/
│   └── orders/
│       ├── main.py
│       ├── core/
│       │   └── settings.py
│       └── api/
│           ├── routes.py
│           └── health.py
└── tests/
    └── test_health.py
```

---

### 重要说明

- TDD驱动模式，完善的单测、集成测试
- 所有测试都需要使用真实环境，不要mock。例如，数据库使用真实数据库等
- 遇到问题优先使用 /systematic-debugging 彻底查明原因，再去解决。解决完之后，一定要验证、跑完所有测试才可以生成完成
- 端口号勿随意修改

