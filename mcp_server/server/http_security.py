"""HTTP security primitives — DNS-rebinding / CORS / CSRF defenses.

Split out of ``http_common`` to keep that module under the 300-line
project ceiling. Every defense targets the same threat surface: a
browser tab visiting an attacker-controlled site attempting to reach
the local Cortex viz server bound on 127.0.0.1.

References:
  * ``validate_host_header`` — CWE-346 / CWE-350 (DNS rebinding).
  * ``resolve_allowed_origin`` / ``_apply_cors_headers`` — CWE-942.
  * ``enforce_same_origin_write`` — CWE-352 (CSRF).
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

# The viz servers are developer tools bound to 127.0.0.1. Any request
# must originate from the same loopback device. We allow both numeric
# loopbacks and the literal ``localhost`` because browsers resolve
# ``http://localhost:<port>`` without going through DNS.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def _host_only(authority: str) -> str:
    """Strip the optional ``:port`` suffix, preserving IPv6 brackets."""
    if not authority:
        return ""
    if authority.startswith("["):
        end = authority.find("]")
        return authority[: end + 1] if end != -1 else authority
    return authority.split(":", 1)[0]


def validate_host_header(handler: BaseHTTPRequestHandler) -> bool:
    """True iff the HTTP Host header names a loopback host.

    DNS-rebinding defense (CWE-346/CWE-350). The server binds 127.0.0.1
    but any hostname can resolve to 127.0.0.1 via DNS rebinding; without
    this check, a site the user visits can issue requests that reach
    this server. An attacker cannot spoof Host from the browser, so
    validating it here is sound.
    """
    host = handler.headers.get("Host", "") or ""
    return _host_only(host.strip()) in _LOOPBACK_HOSTS


def resolve_allowed_origin(handler: BaseHTTPRequestHandler) -> str | None:
    """Return the exact Origin if it's a loopback origin, else None.

    We reflect the value rather than responding with ``*`` so that
    credentials-bearing requests (if ever introduced) are also rejected
    by browsers, and so cross-site pages can never read responses from
    this server.
    """
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return None
    for scheme in ("http://", "https://"):
        if origin.startswith(scheme):
            authority = origin[len(scheme) :]
            if _host_only(authority) in _LOOPBACK_HOSTS:
                return origin
    return None


def enforce_same_origin_write(handler: BaseHTTPRequestHandler) -> bool:
    """For state-changing methods, require a loopback Origin or Referer.

    CSRF defense (CWE-352). Browsers automatically send Origin on
    POST/PUT/DELETE; if it's missing or non-loopback, the request is
    cross-origin and must be rejected. The Referer fallback covers
    browsers/proxies that strip Origin.
    """
    if resolve_allowed_origin(handler) is not None:
        return True
    referer = (handler.headers.get("Referer") or "").strip()
    if not referer:
        return False
    for scheme in ("http://", "https://"):
        if referer.startswith(scheme):
            authority = referer[len(scheme) :].split("/", 1)[0]
            if _host_only(authority) in _LOOPBACK_HOSTS:
                return True
    return False


def _apply_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    """Write the CORS response headers appropriate for this request.

    Strict reflection: echoes the Origin verbatim only if it's loopback.
    Always emits ``Vary: Origin`` so upstream caches key correctly. When
    Origin is absent or non-loopback, no ACAO header is emitted — same-
    origin XHR from the served HTML continues to work; cross-origin
    pages receive a browser-enforced CORS failure.
    """
    allowed = resolve_allowed_origin(handler)
    if allowed is not None:
        handler.send_header("Access-Control-Allow-Origin", allowed)
    handler.send_header("Vary", "Origin")


__all__ = [
    "validate_host_header",
    "resolve_allowed_origin",
    "enforce_same_origin_write",
    "_apply_cors_headers",
]
