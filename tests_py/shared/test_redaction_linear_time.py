"""redact_shapes (scrub_secrets before PR #775) runs in linear time (N2).

The embedded-URL regex retried from every letter of a long letter run: 100 KB
of ``a`` took 8 s, 300 KB about 70 s. The scanner that replaced it must
find exactly the spans the regex found, in time linear in the input.
"""

from __future__ import annotations

import random
import re
import time

from mcp_server.shared.redaction import redact_shapes
from mcp_server.shared.redaction_gate import redact_text

# source: the pattern scrub_secrets used up to PR #775 (ADR-0663)
_REGEX = re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^\s\"'<>]+")
# source: review of PR #775 — 300 KB is 3x the measured 100 KB case (8 s);
# linear code takes about 0.06 s on it, the quadratic regex about 70 s
_BUDGET_S = 5.0


def test_url_spans_match_the_regex_they_replace():
    from mcp_server.shared.redaction import _embedded_urls

    rng = random.Random(1110)
    alphabet = "aZ1+-.:/ \"'<>@xé"
    for _ in range(20_000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        assert list(_embedded_urls(text)) == [m.span() for m in _REGEX.finditer(text)]


def test_a_url_password_is_still_redacted():
    out = redact_shapes("see postgres://u:hunter22@db/x and ftp://a/b")
    assert "hunter22" not in out and "ftp://a/b" in out


def test_long_single_character_runs_stay_linear():
    for unit in ("a", "A", "a:", "password=", "https://"):
        text = unit * (300_000 // len(unit))
        started = time.perf_counter()
        redact_text(text)
        assert time.perf_counter() - started < _BUDGET_S, unit
