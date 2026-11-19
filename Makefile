BACKEND := backend
UV := cd $(BACKEND) && uv run
# tiktoken downloads its BPE file on first use; keep it in a persistent, repo-local cache so
# tests run offline after `make install`.
export TIKTOKEN_CACHE_DIR := $(abspath $(BACKEND)/.cache/tiktoken)

.PHONY: install install-render docker dev dev-backend dev-frontend test test-backend test-frontend lint lint-backend lint-frontend fmt build-frontend types check-vec smoke eval seed

FRONTEND := frontend
NPM := cd $(FRONTEND) && npm
# openapi-typescript peers on TypeScript 5 while the app uses TS 7, so it runs via a pinned npx.
OPENAPI_TS := openapi-typescript@7.13.0

install:
	cd $(BACKEND) && uv sync
	$(UV) python -m scripts.warm_caches
	$(NPM) install

# Optional JS-rendering fallback (JS_RENDER=on): Playwright + headless Chromium (~100 MB).
install-render:
	cd $(BACKEND) && uv sync --extra render
	$(UV) playwright install chromium

# The single production container (API + built frontend + demo seed) on :8000.
docker:
	docker compose up --build

# Backend on :8000 and Vite on :5173 (proxies /api to the backend).
dev:
	$(MAKE) -j2 dev-backend dev-frontend

# Our AccessLogMiddleware emits http.request lines; uvicorn's access log would duplicate them.
dev-backend:
	$(UV) uvicorn app.main:create_app --factory --reload --port 8000 --no-access-log

dev-frontend:
	$(NPM) run dev

test: test-backend test-frontend

test-backend:
	$(UV) pytest

test-frontend:
	$(NPM) test

lint: lint-backend lint-frontend

lint-backend:
	$(UV) ruff check .
	$(UV) ruff format --check .

lint-frontend:
	$(NPM) run lint
	$(NPM) run typecheck

build-frontend:
	$(NPM) run build

# Regenerate frontend API types from the running backend's OpenAPI schema.
types:
	cd $(FRONTEND) && npx -y $(OPENAPI_TS) http://localhost:8000/openapi.json -o src/lib/api-types.ts

fmt:
	$(UV) ruff format .
	$(UV) ruff check --fix .

check-vec:
	$(UV) python -c "import sqlite3, sys; from pathlib import Path; from app.store.db import connect, sqlite_vec_version; c = connect(Path(':memory:')); print(f'python {sys.version.split()[0]}  sqlite {sqlite3.sqlite_version}  sqlite-vec {sqlite_vec_version(c)}')"

# Gate + verifier evaluation with the providers in .env (real calls). Not part of `make test`.
# make eval ARGS="check" | "ablation" | "gate" | "generate --llm openrouter" | "verify llm --run 1" | "report" (see scripts/eval.py)
eval:
	$(UV) python -m scripts.eval $(ARGS)

# Demo data through the normal API: a few notes + the eval URLs from their saved snapshots
# (no web fetches; embeddings use the provider in .env). Skips anything already saved.
seed:
	$(UV) python -m scripts.seed

# Real calls to the providers configured in .env. Not part of `make test`.
smoke:
	$(UV) python -m scripts.smoke
