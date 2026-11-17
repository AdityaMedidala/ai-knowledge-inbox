import ipaddress
import socket
from collections.abc import Sequence
from typing import Any

import pytest

from app.services.url_guard import (
    UrlRejectedError,
    UrlRejection,
    UrlTarget,
    check_peer_address,
    check_resolved_host,
    check_url,
    is_public_ip,
)
from tests.support.dns import fake_resolver


def failing_resolver(errno: int) -> Any:
    def resolve(*_: object, **__: object) -> Sequence[tuple[Any, ...]]:
        raise socket.gaierror(errno, "resolution failed")

    return resolve


def rejection(url: str) -> UrlRejection:
    with pytest.raises(UrlRejectedError) as info:
        check_url(url)
    return info.value.reason


# --- check_url (submit time and every redirect hop; no DNS) ---------------------------------


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("https://example.com/a?b=1", UrlTarget("https", "example.com", 443)),
        ("http://example.com", UrlTarget("http", "example.com", 80)),
        ("http://example.com:443/", UrlTarget("http", "example.com", 443)),
        ("HTTPS://Bücher.Example/", UrlTarget("https", "xn--bcher-kva.example", 443)),
        ("https://93.184.215.14/", UrlTarget("https", "93.184.215.14", 443)),
        ("https://[2606:4700::1111]/", UrlTarget("https", "2606:4700::1111", 443)),
        ("https://localhost.example.com/", UrlTarget("https", "localhost.example.com", 443)),
    ],
)
def test_check_url_accepts_public_targets(url: str, target: UrlTarget) -> None:
    assert check_url(url) == target


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.com/file", UrlRejection.SCHEME),
        ("file:///etc/passwd", UrlRejection.SCHEME),
        ("javascript:alert(1)", UrlRejection.SCHEME),
        ("gopher://example.com:70/", UrlRejection.SCHEME),
        ("https://user:pass@example.com/", UrlRejection.CREDENTIALS),
        ("https://user@example.com/", UrlRejection.CREDENTIALS),
        ("https://@example.com/", UrlRejection.CREDENTIALS),
        ("https://example.com:8080/", UrlRejection.PORT),
        ("http://example.com:22/", UrlRejection.PORT),
        ("https://example.com:0/", UrlRejection.PORT),
        ("https://example.com:99999/", UrlRejection.INVALID),
        ("https://example.com:abc/", UrlRejection.INVALID),
        ("https:///path-only", UrlRejection.INVALID),
        ("not a url", UrlRejection.SCHEME),
    ],
)
def test_check_url_rejects_bad_scheme_credentials_and_ports(url: str, reason: UrlRejection) -> None:
    assert rejection(url) is reason


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1.2.3/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0/",
        "http://224.0.0.1/",  # multicast (is_global is True for some multicast ranges)
        "http://255.255.255.255/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fe80::1%25eth0]/",
        "http://[fd00:ec2::254]/",  # AWS IPv6 metadata
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped
        "http://[::ffff:169.254.169.254]/",
        "http://[64:ff9b::7f00:1]/",  # NAT64 wrapping 127.0.0.1
        "http://[ff02::1]/",
        "http://[2002:7f00:1::]/",  # 6to4 wrapping 127.0.0.1
    ],
)
def test_check_url_rejects_literal_non_public_ips(url: str) -> None:
    assert rejection(url) is UrlRejection.ADDRESS


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST./",
        "http://api.localhost/",
        "http://printer.local/",
        "http://metadata.google.internal/",
        "http://router.home.arpa/",
    ],
)
def test_check_url_rejects_local_hostnames(url: str) -> None:
    assert rejection(url) is UrlRejection.HOST


def test_rejection_message_never_echoes_the_url() -> None:
    with pytest.raises(UrlRejectedError) as info:
        check_url("https://user:hunter2@example.com/")
    assert "hunter2" not in info.value.message


# --- check_resolved_host (worker side, injected resolver) ----------------------------------


def test_public_resolution_passes_and_returns_addresses() -> None:
    resolver = fake_resolver("93.184.215.14", "2606:4700::1111", "93.184.215.14")
    addresses = check_resolved_host("example.com", 443, resolver)
    assert addresses == [
        ipaddress.ip_address("93.184.215.14"),
        ipaddress.ip_address("2606:4700::1111"),
    ]
    assert resolver.queried == ["example.com"]


@pytest.mark.parametrize(
    "ips",
    [
        ("127.0.0.1",),
        ("10.1.2.3",),
        ("169.254.169.254",),
        ("::1",),
        ("::ffff:10.0.0.1",),
        ("fe80::1%en0",),
        ("93.184.215.14", "192.168.0.10"),  # ANY non-public address blocks
        ("2606:4700::1111", "fd12::1"),
    ],
)
def test_resolution_to_any_non_public_address_is_blocked(ips: tuple[str, ...]) -> None:
    with pytest.raises(UrlRejectedError) as info:
        check_resolved_host("evil.example", 443, fake_resolver(*ips))
    assert info.value.reason is UrlRejection.ADDRESS


def test_integer_host_passes_syntax_check_but_is_caught_on_resolution() -> None:
    target = check_url("http://2130706433/")  # getaddrinfo reads this as 127.0.0.1
    with pytest.raises(UrlRejectedError) as info:
        check_resolved_host(target.host, target.port, fake_resolver("127.0.0.1"))
    assert info.value.reason is UrlRejection.ADDRESS


@pytest.mark.parametrize(
    ("errno", "transient"), [(socket.EAI_NONAME, False), (socket.EAI_AGAIN, True)]
)
def test_resolution_failure_is_unresolvable(errno: int, transient: bool) -> None:
    with pytest.raises(UrlRejectedError) as info:
        check_resolved_host("nope.example", 443, failing_resolver(errno))
    assert info.value.reason is UrlRejection.UNRESOLVABLE
    assert info.value.transient is transient


def test_empty_resolution_is_unresolvable() -> None:
    with pytest.raises(UrlRejectedError) as info:
        check_resolved_host("empty.example", 443, fake_resolver())
    assert info.value.reason is UrlRejection.UNRESOLVABLE


def test_default_resolver_is_socket_getaddrinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = fake_resolver("10.0.0.1")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    with pytest.raises(UrlRejectedError):
        check_resolved_host("internal-by-dns.example", 80)
    assert resolver.queried == ["internal-by-dns.example"]


# --- check_peer_address (after connect, before reading the body) ---------------------------


@pytest.mark.parametrize("sockaddr", [("93.184.215.14", 443), ("2606:4700::1111", 443, 0, 0)])
def test_public_peer_passes(sockaddr: tuple[Any, ...]) -> None:
    assert is_public_ip(check_peer_address(sockaddr))


@pytest.mark.parametrize(
    "sockaddr", [("127.0.0.1", 80), ("::ffff:192.168.1.1", 80, 0, 0), ("garbage", 80), ()]
)
def test_non_public_or_unknown_peer_is_blocked(sockaddr: tuple[Any, ...]) -> None:
    with pytest.raises(UrlRejectedError) as info:
        check_peer_address(sockaddr)
    assert info.value.reason is UrlRejection.ADDRESS
