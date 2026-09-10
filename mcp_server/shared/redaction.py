"""Pure secret-redaction utilities for the shared layer.

source: ADR-0663"""

from __future__ import annotations

import re
import urllib.parse

# ── Constants ─────────────────────────────────────────────────────────────

_PASSWORD_MASK = "***"
_REDACTED = "[REDACTED]"

# ── redact_url ─────────────────────────────────────────────────────────────


def redact_url(url: str) -> str:
    """Mask the password component of a database/connection URL.

    Pre:  url is a str.
    Post: the returned URL has the password masked in BOTH locations where
          it may appear:
            (a) userinfo field  — ``user:secret@host`` → ``user:***@host``
            (b) query parameter — ``?password=secret`` → ``?password=***``
                (keys matched case-insensitively: ``password``, ``pgpassword``)
          URLs without a password, and strings that are not URLs, are returned
          unchanged.
          IPv6 hosts are preserved with brackets (``[::1]``).

    Examples:
        redact_url("postgresql://user:secret@host:5432/db")
            -> "postgresql://user:***@host:5432/db"
        redact_url("postgresql://cortex@localhost/cortex?password=s&sslmode=require")
            -> "postgresql://cortex@localhost/cortex?password=***&sslmode=require"
        redact_url("postgres://u:secret@[::1]:5432/db")
            -> "postgres://u:***@[::1]:5432/db"
        redact_url("postgresql://host/db")
            -> "postgresql://host/db"          (no password — unchanged)
        redact_url("not a url")
            -> "not a url"                     (not a URL — unchanged)
    """
    # precondition: url must be a str
    if not isinstance(url, str) or not url:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return url  # postcondition: non-parseable → unchanged

    # source: ADR-0663

    if not parsed.scheme:
        return url

    # ── (a) userinfo password ──────────────────────────────────────────────
    userinfo_changed = False
    if parsed.password:
        user = parsed.username or ""
        # source: ADR-0663

        raw_host = parsed.hostname or ""
        host = f"[{raw_host}]" if ":" in raw_host else raw_host
        port = parsed.port

        if port is not None:
            netloc = f"{user}:{_PASSWORD_MASK}@{host}:{port}"
        else:
            netloc = f"{user}:{_PASSWORD_MASK}@{host}"

        userinfo_changed = True
    else:
        netloc = parsed.netloc  # unchanged

    # ── (b) query-parameter password (libpq DSN style) ────────────────────
    # Keys matched case-insensitively; order of other params is preserved.
    _password_query_keys = frozenset({"password", "pgpassword"})
    query_changed = False
    new_query = parsed.query
    if parsed.query:
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        masked_pairs = []
        for key, value in pairs:
            if key.lower() in _password_query_keys and value:
                masked_pairs.append((key, _PASSWORD_MASK))
                query_changed = True
            else:
                masked_pairs.append((key, value))
        if query_changed:
            new_query = urllib.parse.urlencode(masked_pairs)

    if not userinfo_changed and not query_changed:
        return url  # postcondition: no password anywhere — unchanged

    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


# ── Self-check assertions (run once at import; caught by python3 -m py_compile
#    equivalents and by the test suite) ────────────────────────────────────────


def _selfcheck() -> None:
    """Regression assertions for the two confirmed leak vectors.

    source: ADR-0663
    """
    # Repro: query-parameter password must be masked.
    _qp = redact_url(
        "postgresql://cortex@localhost:5432/cortex?password=SuperSecret123&sslmode=require"
    )
    assert "SuperSecret123" not in _qp, f"query-param password leak: {_qp!r}"
    # source: ADR-0663
    assert "password=***" in _qp or "password=%2A%2A%2A" in _qp, (
        f"expected masked password in: {_qp!r}"
    )
    assert "sslmode=require" in _qp, f"sslmode param lost: {_qp!r}"

    # Repro: IPv6 host must keep brackets.
    _ipv6 = redact_url("postgres://u:secret@[::1]:5432/db")
    assert "secret" not in _ipv6, f"IPv6 userinfo password leak: {_ipv6!r}"
    assert "[::1]" in _ipv6, f"IPv6 brackets dropped: {_ipv6!r}"


_selfcheck()


# ── scrub_secrets ──────────────────────────────────────────────────────────

# source: ADR-0663


# source: ADR-0663


_RE_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# source: ADR-0663


_RE_BEARER_TOKEN = re.compile(r"\bbearer\s+([A-Za-z0-9\-_\.+/=]{8,})", re.IGNORECASE)

# source: ADR-0663


_RE_KV_SECRET = re.compile(
    r"(?i)\b(password|token|api[_\-]?key|secret[_\-]?key?|private[_\-]?key)"
    r"\s*[:=]\s*"
    r"(['\"]?)([^\s'\"]{4,})\2",
)

# source: ADR-0663


_RE_PEM_PRIVATE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)

# source: ADR-0663


_RE_EMBEDDED_URL = re.compile(
    r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^\s\"'<>]+",
)


def scrub_secrets(text: str) -> str:
    """Replace recognized secret shapes in ``text`` with ``[REDACTED]``.

    source: ADR-0663

    Pre:  text is a str.
    Post: the returned string has all recognized secret-shaped tokens
          replaced with the ``[REDACTED]`` placeholder.  Content that does
          not match a known secret shape is unchanged.

    source: ADR-0663

    Patterns covered (in application order):
      1. PEM private-key blocks.
      2. AWS access key IDs (AKIA…).
      3. Bearer / Authorization tokens.
      4. key=value / key: value secret assignments.
      5. Embedded URL passwords (via redact_url).
    """
    # precondition: text must be a str
    if not isinstance(text, str) or not text:
        return text

    # source: ADR-0663
    text = _RE_PEM_PRIVATE.sub(_REDACTED, text)

    # 2. AWS access key IDs.
    text = _RE_AWS_ACCESS_KEY.sub(_REDACTED, text)

    # 3. Bearer / Authorization tokens — keep the "bearer" word, mask value.
    text = _RE_BEARER_TOKEN.sub(lambda m: f"bearer {_REDACTED}", text)

    # 4. key=value secret assignments — keep key name, mask value.
    #    Group 1: key name; group 2: optional quote char; group 3: value.
    text = _RE_KV_SECRET.sub(lambda m: f"{m.group(1)}={_REDACTED}", text)

    # 5. Embedded URL passwords: find URL-shaped substrings and redact each.
    def _redact_url_match(m: re.Match) -> str:
        return redact_url(m.group(0))

    return _RE_EMBEDDED_URL.sub(_redact_url_match, text)
