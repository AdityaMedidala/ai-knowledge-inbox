"""Block every real network connection in tests; only loopback and unix sockets are allowed."""

import socket
from collections.abc import Callable
from typing import Any

import pytest

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", None})


class NetworkBlockedError(RuntimeError):
    pass


class NetworkGuard:
    def __init__(self) -> None:
        self.blocked: list[str] = []

    def check(self, host: object, port: object) -> None:
        if host in ALLOWED_HOSTS:
            return
        target = f"{host}:{port}"
        self.blocked.append(target)
        raise NetworkBlockedError(f"Network access blocked in tests: {target}")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_create_connection = socket.create_connection
        real_getaddrinfo = socket.getaddrinfo

        def guard_method(real: Callable[..., Any]) -> Callable[..., Any]:
            def guarded(sock: socket.socket, address: Any) -> Any:
                if sock.family != getattr(socket, "AF_UNIX", object()):
                    self.check(*address[:2])
                return real(sock, address)

            return guarded

        def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
            self.check(*address[:2])
            return real_create_connection(address, *args, **kwargs)

        def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            self.check(host, port)
            return real_getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", guard_method(real_connect))
        monkeypatch.setattr(socket.socket, "connect_ex", guard_method(real_connect_ex))
        monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
        monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
