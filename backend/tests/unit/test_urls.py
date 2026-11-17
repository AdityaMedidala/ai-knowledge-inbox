import pytest

from app.utils.urls import UNPARSEABLE_URL, normalize_url, redact_url, to_ascii_host


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),  # path case is significant
        ("https://example.com", "https://example.com/"),
        ("https://example.com/", "https://example.com/"),
        ("https://example.com/a/b/", "https://example.com/a/b"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("http://example.com:443/a", "http://example.com:443/a"),  # not the default for http
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        (
            "https://example.com/a?utm_source=x&UTM_Medium=y&fbclid=1&gclid=2&id=7",
            "https://example.com/a?id=7",
        ),
        ("https://example.com/a?utm_source=x", "https://example.com/a"),
        ("https://example.com/a?flag=&x=1", "https://example.com/a?flag=&x=1"),
        ("https://user:pw@example.com/a", "https://example.com/a"),
        ("https://example.com./a", "https://example.com/a"),
        ("https://bücher.example/a", "https://xn--bcher-kva.example/a"),
        ("http://[2606:4700::1111]:8080/", "http://[2606:4700::1111]:8080/"),
        ("  https://example.com/a  ", "https://example.com/a"),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


def test_normalize_url_makes_equivalent_urls_equal() -> None:
    variants = [
        "https://Example.com/post/?b=2&a=1&utm_campaign=z#top",
        "https://example.com:443/post?a=1&b=2",
        "HTTPS://EXAMPLE.COM/post/?a=1&b=2&fbclid=abc",
    ]
    assert len({normalize_url(url) for url in variants}) == 1


@pytest.mark.parametrize("url", ["https:///no-host", "https://example.com:99999/", "http://:80/"])
def test_normalize_url_rejects_unparseable(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a/b?token=SECRET#frag", "https://example.com/a/b"),
        ("https://user:pw@example.com/a", "https://example.com/a"),
        ("http://example.com:8080/x?k=v", "http://example.com:8080/x"),
        ("https://[::1]/admin?key=1", "https://[::1]/admin"),
        ("https://example.com:notaport/", UNPARSEABLE_URL),
    ],
)
def test_redact_url_keeps_only_scheme_host_port_path(url: str, expected: str) -> None:
    redacted = redact_url(url)
    assert redacted == expected
    assert "SECRET" not in redacted and "pw" not in redacted


def test_to_ascii_host_rejects_empty() -> None:
    with pytest.raises(ValueError):
        to_ascii_host(" . ")
