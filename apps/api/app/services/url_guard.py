"""Validation of user-supplied media URLs before they reach yt-dlp (SSRF defence)."""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443})
_MAX_URL_LENGTH = 2048

Resolver = Callable[[str, int], Sequence[str]]


class UnsafeUrlError(ValueError):
    """The URL is malformed or points somewhere the server must not fetch."""


def _system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_public(ip.ipv4_mapped)
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def validate_public_url(url: str, resolver: Resolver = _system_resolver) -> str:
    """Return the normalised URL if it is http(s) and every resolved address is public.

    Rejects: other schemes, embedded credentials, non-standard ports, literal or resolved
    private/loopback/link-local/CGNAT/metadata addresses, and hosts that do not resolve.
    """
    candidate = url.strip()
    if not candidate or len(candidate) > _MAX_URL_LENGTH:
        raise UnsafeUrlError("URL is empty or too long")
    if any(ch.isspace() or ord(ch) < 0x20 for ch in candidate):
        raise UnsafeUrlError("URL contains whitespace or control characters")

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URLs with credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("URL has an invalid port") from exc
    if port not in _ALLOWED_PORTS:
        raise UnsafeUrlError("Only ports 80 and 443 are allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses: Sequence[str] = [str(literal)]
    else:
        if host.endswith((".localhost", ".local", ".internal")) or host == "localhost":
            raise UnsafeUrlError("Internal hostnames are not allowed")
        try:
            addresses = resolver(host, port)
        except (OSError, UnicodeError) as exc:
            raise UnsafeUrlError("Host could not be resolved") from exc
        if not addresses:
            raise UnsafeUrlError("Host could not be resolved")

    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeUrlError("Host resolved to an invalid address") from exc
        if not _is_public(ip):
            raise UnsafeUrlError("URL points to a private or reserved network address")

    return parts.geturl()
