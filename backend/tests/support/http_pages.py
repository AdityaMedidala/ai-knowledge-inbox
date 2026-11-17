"""Fake HTTP responses as httpx2 would deliver them from a real socket (for MockRouter routes)."""

from collections.abc import Iterator
from typing import Any

import httpx2

from tests.support.dns import PUBLIC_PEER

HTML = b"<html><head><title>T</title></head><body><p>Hello</p></body></html>"


class FakeNetworkStream:
    """What httpcore2 exposes as response.extensions['network_stream']."""

    def __init__(self, peer: tuple[Any, ...] | None) -> None:
        self.peer = peer

    def get_extra_info(self, info: str) -> Any:
        return self.peer if info == "server_addr" else None


def page(
    status: int = 200,
    body: bytes | Iterator[bytes] = HTML,
    content_type: str | None = "text/html; charset=utf-8",
    peer: tuple[Any, ...] | None = PUBLIC_PEER,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    all_headers = {"content-type": content_type} if content_type else {}
    all_headers |= headers or {}
    return httpx2.Response(
        status,
        headers=all_headers,
        # Always a stream: bytes content would be read (and decoded) eagerly at construction,
        # whereas a real connection decodes inside the fetcher's iter_bytes loop.
        content=iter([body]) if isinstance(body, bytes) else body,
        extensions={"network_stream": FakeNetworkStream(peer)},
    )


def redirect(location: str, status: int = 302) -> httpx2.Response:
    return page(status, b"", headers={"location": location})
