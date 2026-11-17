"""Pure URL helpers: host canonicalisation, the duplicate-detection key, and log-safe redaction."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}
TRACKING_PARAMS = frozenset({"fbclid", "gclid"})
TRACKING_PREFIX = "utm_"
UNPARSEABLE_URL = "[unparseable url]"


def to_ascii_host(host: str) -> str:
    """Lowercase, strip the root-zone dot, IDNA-encode. Raises ValueError for an unusable host.

    IPv6 literals (as returned by urlsplit().hostname, without brackets) are returned unchanged.
    """
    host = host.strip().rstrip(".").lower()
    if not host:
        raise ValueError("URL has no host.")
    if ":" in host:
        return host
    return host.encode("idna").decode("ascii")  # UnicodeError is a ValueError


def normalize_url(url: str) -> str:
    """Canonical form used as the duplicate key. Never fetched: the submitted URL is.

    Lowercases scheme and host, IDNA-encodes the host, drops userinfo, the default port, the
    fragment and tracking parameters, sorts the query, and strips a trailing slash except at root.
    Raises ValueError if the URL cannot be parsed.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = to_ascii_host(parts.hostname or "")
    netloc = f"[{host}]" if ":" in host else host
    port = parts.port  # raises ValueError on a non-numeric or out-of-range port
    if port is not None and port != DEFAULT_PORTS.get(scheme):
        netloc += f":{port}"

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    params = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode(sorted((key, value) for key, value in params if not _is_tracking(key)))
    return urlunsplit((scheme, netloc, path, query, ""))


def redact_url(url: str) -> str:
    """scheme://host[:port]/path for logs: query strings and fragments can carry secrets."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return UNPARSEABLE_URL
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, "", ""))


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIX)
