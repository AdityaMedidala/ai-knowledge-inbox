#!/bin/sh
# Container entrypoint. Starts as root only to make the data volume writable (Railway and fresh
# Docker volumes mount it root-owned), then drops to the unprivileged `app` user.
set -eu
DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R app:app "$DATA_DIR"
    exec setpriv --reuid=app --regid=app --init-groups -- "$0" "$@"
fi

# One worker: SQLite + the in-process ingestion queue and demo rate limits assume one process.
exec uvicorn app.main:create_app --factory \
    --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --no-access-log
