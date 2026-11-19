"""What the headless browser may load: the fetcher's SSRF rules, applied to every request."""

import socket

import pytest

from app.services.renderer import RequestGuard


def resolving_to(address: str):
    def resolve(host: str, port: int, **_: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return resolve


PUBLIC = RequestGuard(resolver=resolving_to("93.184.216.34"))


@pytest.mark.parametrize("resource_type", ["image", "media", "font"])
def test_heavy_resources_are_refused(resource_type: str) -> None:
    assert (
        PUBLIC.rejection("https://example.com/a", resource_type) == f"resource_type_{resource_type}"
    )


@pytest.mark.parametrize("resource_type", ["document", "script", "xhr", "fetch", "stylesheet"])
def test_public_requests_are_allowed(resource_type: str) -> None:
    assert PUBLIC.rejection("https://example.com/app.js", resource_type) is None


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://169.254.169.254/latest/meta-data/", "address_not_allowed"),
        ("http://10.0.0.1/", "address_not_allowed"),
        ("http://[::1]/", "address_not_allowed"),
        ("http://[::ffff:127.0.0.1]/", "address_not_allowed"),
        ("http://localhost/", "host_not_allowed"),
        ("https://example.com:8443/", "port_not_allowed"),
        ("ftp://example.com/", "scheme_not_allowed"),
        ("file:///etc/passwd", "scheme_not_allowed"),
    ],
)
def test_private_targets_bad_ports_and_schemes_are_refused(url: str, reason: str) -> None:
    assert PUBLIC.rejection(url, "fetch") == reason


def test_a_name_resolving_to_a_private_address_is_refused() -> None:
    guard = RequestGuard(resolver=resolving_to("192.168.1.10"))
    assert guard.rejection("https://intranet.example.com/", "document") == "address_not_allowed"


def test_allowed_hosts_bypass_the_guard_for_tests_only() -> None:
    guard = RequestGuard(resolver=resolving_to("127.0.0.1"), allowed_hosts=frozenset({"127.0.0.1"}))
    assert guard.rejection("http://127.0.0.1:8123/page", "document") is None
    assert guard.rejection("http://10.0.0.1/", "fetch") == "address_not_allowed"
