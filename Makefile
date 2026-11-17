BACKEND := backend
UV := cd $(BACKEND) && uv run
# tiktoken downloads its BPE file on first use; keep it in a persistent, repo-local cache so
# tests run offline after `make install`.
export TIKTOKEN_CACHE_DIR := $(abspath $(BACKEND)/.cache/tiktoken)

.PHONY: install dev dev-backend test lint fmt check-vec smoke-openai

install:
	cd $(BACKEND) && uv sync
	$(UV) python -c "from app.utils.tokens import count_tokens; count_tokens('warm cache')"

dev: dev-backend

# Our AccessLogMiddleware emits http.request lines; uvicorn's access log would duplicate them.
dev-backend:
	$(UV) uvicorn app.main:create_app --factory --reload --port 8000 --no-access-log

test:
	$(UV) pytest

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

fmt:
	$(UV) ruff format .
	$(UV) ruff check --fix .

check-vec:
	$(UV) python -c "import sqlite3, sys; from pathlib import Path; from app.store.db import connect, sqlite_vec_version; c = connect(Path(':memory:')); print(f'python {sys.version.split()[0]}  sqlite {sqlite3.sqlite_version}  sqlite-vec {sqlite_vec_version(c)}')"

# Real API calls using .env (costs a fraction of a cent). Not part of `make test`.
smoke-openai:
	$(UV) python -m scripts.smoke_openai
