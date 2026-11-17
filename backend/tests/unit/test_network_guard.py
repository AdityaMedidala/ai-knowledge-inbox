import socket

import pytest

from tests.support.network_guard import NetworkBlockedError, NetworkGuard


def test_guard_blocks_real_hosts(network_guard: NetworkGuard) -> None:
    with pytest.raises(
        NetworkBlockedError, match=r"Network access blocked in tests: api\.openai\.com:443"
    ):
        socket.create_connection(("api.openai.com", 443), timeout=1)
    with pytest.raises(NetworkBlockedError, match=r"api\.openai\.com:443"):
        socket.getaddrinfo("api.openai.com", 443)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(NetworkBlockedError, match=r"93\.184\.215\.14:80"):
        sock.connect(("93.184.215.14", 80))
    sock.close()
    assert network_guard.blocked == ["api.openai.com:443", "api.openai.com:443", "93.184.215.14:80"]
    network_guard.blocked.clear()  # expected attempts in this test only


def test_guard_allows_loopback() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname(), timeout=1)
    client.close()
    server.close()
    assert socket.getaddrinfo("localhost", 80)
