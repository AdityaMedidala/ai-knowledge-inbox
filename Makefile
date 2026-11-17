BACKEND := backend
UV := cd $(BACKEND) && uv run

.PHONY: install dev dev-backend test lint fmt check-vec

install:
	cd $(BACKEND) && uv sync

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
