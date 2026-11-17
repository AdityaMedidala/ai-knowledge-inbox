"""SSRF guard. Three checks, all raising UrlRejectedError:

- check_url: pure syntax/policy check (no DNS). Used at submit time and on every redirect hop.
- check_resolved_host: resolves the host and rejects if ANY address is not globally routable.
- check_peer_address: re-checks the address the socket actually connected to (DNS rebinding).
"""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from app.utils.urls import DEFAULT_PORTS, to_ascii_host

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[..., Sequence[tuple[Any, ...]]]  # socket.getaddrinfo-compatible

ALLOWED_PORTS = frozenset(DEFAULT_PORTS.values())
# Names that always mean "this machine / this private network" (RFC 6761, 6762, 8375, ICANN).
BLOCKED_HOST_SUFFIXES = ("localhost", "local", "internal", "home.arpa")
# NAT64 prefixes embed an IPv4 address in the low 32 bits; is_global ignores what it points at.
NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


class UrlRejection(StrEnum):
    INVALID = "invalid_url"
    SCHEME = "scheme_not_allowed"
    CREDENTIALS = "credentials_in_url"
    PORT = "port_not_allowed"
    HOST = "host_not_allowed"
    ADDRESS = "address_not_allowed"
    UNRESOLVABLE = "host_unresolvable"


class UrlRejectedError(Exception):
    """`message` is safe to show the user: it never echoes the URL back."""

    def __init__(self, reason: UrlRejection, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.transient = transient  # only for UNRESOLVABLE: a temporary DNS failure


@dataclass(frozen=True, slots=True)
class UrlTarget:
    scheme: str
    host: str  # ASCII (IDNA) form, no brackets for IPv6
    port: int


def check_url(url: str) -> UrlTarget:
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise UrlRejectedError(UrlRejection.INVALID, "The URL is not valid.") from exc
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise UrlRejectedError(UrlRejection.SCHEME, "Only http and https URLs are allowed.")
    try:
        explicit_port = parts.port
        host = to_ascii_host(parts.hostname or "")
    except ValueError as exc:
        raise UrlRejectedError(UrlRejection.INVALID, "The URL is not valid.") from exc

    if "@" in parts.netloc:
        raise UrlRejectedError(
            UrlRejection.CREDENTIALS, "URLs with embedded credentials are not allowed."
        )
    if explicit_port is not None and explicit_port not in ALLOWED_PORTS:
        raise UrlRejectedError(UrlRejection.PORT, "Only ports 80 and 443 are allowed.")

    literal_ip = _parse_ip(host)
    if literal_ip is not None and not is_public_ip(literal_ip):
        raise UrlRejectedError(
            UrlRejection.ADDRESS, "URLs pointing at private or local addresses are not allowed."
        )
    if literal_ip is None and _is_blocked_hostname(host):
        raise UrlRejectedError(
            UrlRejection.HOST, "URLs pointing at local hostnames are not allowed."
        )
    return UrlTarget(scheme, host, explicit_port or DEFAULT_PORTS[scheme])


def check_resolved_host(host: str, port: int, resolver: Resolver | None = None) -> list[IPAddress]:
    """Resolve and vet every address. Returns them so callers can log or pin them."""
    resolve = resolver or socket.getaddrinfo  # looked up per call so tests can patch socket
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlRejectedError(
            UrlRejection.UNRESOLVABLE,
            "The site's hostname could not be resolved.",
            transient=exc.errno == socket.EAI_AGAIN,
        ) from exc

    addresses = list(dict.fromkeys(ip for info in infos if (ip := _sockaddr_ip(info[4]))))
    if not addresses:
        raise UrlRejectedError(
            UrlRejection.UNRESOLVABLE, "The site's hostname could not be resolved."
        )
    if any(not is_public_ip(address) for address in addresses):
        raise UrlRejectedError(
            UrlRejection.ADDRESS, "The site resolves to a private or local address."
        )
    return addresses


def check_peer_address(sockaddr: tuple[Any, ...]) -> IPAddress:
    """Vet the connected peer (`network_stream.get_extra_info('server_addr')`)."""
    address = _sockaddr_ip(sockaddr)
    if address is None or not is_public_ip(address):
        raise UrlRejectedError(
            UrlRejection.ADDRESS, "The site connected to a private or local address."
        )
    return address


def is_public_ip(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_ip(address.ipv4_mapped)
        if any(address in network for network in NAT64_NETWORKS):
            return is_public_ip(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return address.is_global and not address.is_multicast


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return None


def _sockaddr_ip(sockaddr: tuple[Any, ...]) -> IPAddress | None:
    return _parse_ip(str(sockaddr[0])) if sockaddr else None


def _is_blocked_hostname(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in BLOCKED_HOST_SUFFIXES)
