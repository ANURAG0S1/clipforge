from collections.abc import Sequence

import pytest

from app.services.url_guard import Resolver, UnsafeUrlError, validate_public_url


def _resolver(mapping: dict[str, list[str]]) -> Resolver:
    def resolve(host: str, port: int) -> Sequence[str]:
        if host not in mapping:
            raise OSError("NXDOMAIN")
        return mapping[host]

    return resolve


PUBLIC = _resolver(
    {
        "www.youtube.com": ["142.250.80.46", "2607:f8b0:4006:80f::200e"],
        "cdn.example.com": ["93.184.216.34"],
        "evil.example.com": ["93.184.216.34", "10.0.0.5"],
        "rebind.example.com": ["127.0.0.1"],
        "metadata.example.com": ["169.254.169.254"],
        "v6local.example.com": ["::1"],
        "mapped.example.com": ["::ffff:192.168.1.1"],
        "cgnat.example.com": ["100.64.1.1"],
    }
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "http://cdn.example.com/video.mp4",
        "https://cdn.example.com:443/video.mp4",
        "  https://cdn.example.com/a  ",
    ],
)
def test_public_urls_allowed(url: str) -> None:
    assert validate_public_url(url, resolver=PUBLIC).startswith("http")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://cdn.example.com/video.mp4", "Only http and https"),
        ("file:///etc/passwd", "Only http and https"),
        ("gopher://cdn.example.com", "Only http and https"),
        ("javascript:alert(1)", "Only http and https"),
        ("https://user:pass@cdn.example.com/v.mp4", "credentials"),
        ("https://cdn.example.com:8080/v.mp4", "ports"),
        ("http://127.0.0.1/admin", "private"),
        ("http://10.1.2.3/", "private"),
        ("http://192.168.0.10/", "private"),
        ("http://172.16.5.5/", "private"),
        ("http://169.254.169.254/latest/meta-data/", "private"),
        ("http://[::1]/", "private"),
        ("http://0.0.0.0/", "private"),
        ("http://localhost/", "Internal hostnames"),
        ("http://api.internal/", "Internal hostnames"),
        ("http://evil.example.com/", "private"),
        ("http://rebind.example.com/", "private"),
        ("http://metadata.example.com/", "private"),
        ("http://v6local.example.com/", "private"),
        ("http://mapped.example.com/", "private"),
        ("http://cgnat.example.com/", "private"),
        ("http://does-not-exist.example.com/", "could not be resolved"),
        ("http:///nohost", "no host"),
        ("", "empty"),
        ("https://cdn.example.com/a b", "whitespace"),
        ("https://cdn.example.com:99999/", "invalid port"),
    ],
)
def test_unsafe_urls_rejected(url: str, reason: str) -> None:
    with pytest.raises(UnsafeUrlError, match=reason):
        validate_public_url(url, resolver=PUBLIC)


def test_overlong_url_rejected() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://cdn.example.com/" + "a" * 3000, resolver=PUBLIC)
