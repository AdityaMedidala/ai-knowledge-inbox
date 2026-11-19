"""Starts the optional headless-browser renderer (JS_RENDER=on) or fails startup clearly."""

from typing import Protocol

from app.config import Settings
from app.domain.errors import RenderSetupError
from app.services.renderer import PageRenderer

INSTALL_HINT = (
    "JS_RENDER=on needs Playwright and Chromium. Install them with "
    "`cd backend && uv sync --extra render && uv run playwright install chromium`, "
    "or set JS_RENDER=off."
)


class ClosableRenderer(PageRenderer, Protocol):
    async def close(self) -> None: ...


async def start_renderer(settings: Settings) -> ClosableRenderer | None:
    if settings.js_render == "off":
        return None
    try:
        # Optional dependency: imported only when rendering is switched on.
        from app.services.browser_renderer import PlaywrightRenderer
    except ImportError as exc:
        raise RenderSetupError(f"Playwright is not installed. {INSTALL_HINT}") from exc
    try:
        return await PlaywrightRenderer.start(
            timeout_s=settings.render_timeout_s,
            max_bytes=settings.fetch_max_bytes,
            max_pages=settings.render_max_pages,
            max_redirects=settings.fetch_max_redirects,
        )
    except RenderSetupError as exc:
        raise RenderSetupError(f"{exc} {INSTALL_HINT}") from exc
