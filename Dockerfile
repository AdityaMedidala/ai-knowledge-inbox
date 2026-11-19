# syntax=docker/dockerfile:1.7
# One container: FastAPI serves the API and the built frontend on the same origin.

# --- 1. frontend build ------------------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Python dependencies + baked models (uv and its cache stay in this stage) ---------------
FROM python:3.12-slim AS python-deps
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
# The venv must use the base image's interpreter: the runtime stage has the same one, and no
# uv-managed Python (which would live under /root and be missing at runtime).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    FASTEMBED_CACHE_DIR=/opt/models/fastembed \
    TIKTOKEN_CACHE_DIR=/opt/models/tiktoken
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
# No dev deps, no optional extras (no Playwright). No cache mount: Railway only accepts one with
# a service-specific id; uv's cache stays in this stage and never reaches the runtime image.
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/scripts/__init__.py backend/scripts/warm_caches.py ./scripts/
# The tokenizer and the bge-small embedding model, so the app runs offline.
RUN LLM_PROVIDER=fake /app/.venv/bin/python -m scripts.warm_caches

# --- 3. runtime -------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    FASTEMBED_CACHE_DIR=/opt/models/fastembed \
    TIKTOKEN_CACHE_DIR=/opt/models/tiktoken \
    FRONTEND_DIST=/app/static \
    SEED_DIR=/app/seed \
    DATA_DIR=/data \
    LOG_JSON=true
WORKDIR /app
RUN useradd --system --uid 1000 --home-dir /app app

COPY --from=python-deps /app/.venv /app/.venv
COPY --from=python-deps /opt/models /opt/models
COPY backend/app ./app
COPY backend/eval/eval_set.json ./seed/eval_set.json
COPY backend/eval/corpus ./seed/corpus
COPY --from=frontend /src/frontend/dist ./static
COPY docker/start.sh ./start.sh

# /data is where the volume goes (compose: named volume; Railway: a service Volume). No VOLUME
# instruction: Railway rejects it, and both platforms attach the volume explicitly.
RUN mkdir -p /data && chown app:app /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=4)"
CMD ["/app/start.sh"]
