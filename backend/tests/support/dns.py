"""getaddrinfo stand-ins, so SSRF checks run against simulated DNS (never the real resolver)."""

import socket
from collections.abc import Mapping, Sequence
from typing import Any

PUBLIC_IP = "93.184.215.14"
PUBLIC_PEER = (PUBLIC_IP, 443)


class FakeResolver:
    """Hosts in `records` resolve to their IPs; others to `default`, or NXDOMAIN if None."""

    def __init__(
        self,
        records: Mapping[str, Sequence[str]] | None = None,
        *,
        default: Sequence[str] | None = None,
    ) -> None:
        self.records = dict(records or {})
        self.default = default
        self.queried: list[str] = []

    def __call__(self, host: str, port: int, **_: object) -> list[tuple[Any, ...]]:
        self.queried.append(host)
        ips = self.records.get(host, self.default)
        if ips is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [_info(ip, port) for ip in ips]


def fake_resolver(*ips: str) -> FakeResolver:
    """Resolve every host to `ips`."""
    return FakeResolver(default=ips)


def _info(ip: str, port: int) -> tuple[Any, ...]:
    if ":" in ip:
        return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
