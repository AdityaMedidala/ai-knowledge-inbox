"""Serve the built frontend from the API process (FRONTEND_DIST): one origin, so no CORS.

The frontend calls the API under /api (in development Vite's proxy strips the prefix); here a
small ASGI wrapper strips it, so the routes stay at / for tests, OpenAPI and direct use.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

API_PREFIX = "/api"


class StripApiPrefix:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            if path == API_PREFIX or path.startswith(f"{API_PREFIX}/"):
                stripped = path[len(API_PREFIX) :] or "/"
                scope = {**scope, "path": stripped, "raw_path": stripped.encode()}
        await self.app(scope, receive, send)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Call after the API routers, so API routes win over static files."""
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"FRONTEND_DIST={dist} has no index.html; build the frontend first.")
    app.add_middleware(StripApiPrefix)
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
