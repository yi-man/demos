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
	uv sync --python $(PYTHON_VERSION) --frozen --extra dev

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

