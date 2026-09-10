# ADR-0716: scripts/check_venv_lock_parity.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/check_venv_lock_parity.py`; original SHA-256 `1b754aac2ec4d3ce35923aadd2daa90c60a48c4d599f80d9acdf1ff0974ba94a`.

## Original docstring, lines 2–35

````text
"""Guard a stale postgresql-extra install from silently under-collecting
tests (issue #287).

`tests_py/infrastructure/test_pg_*.py` (and its siblings across
`tests_py/integration/`, `tests_py/invariants/`) gate on
``pytest.importorskip("psycopg", ...)`` so a SQLite-only dev install
intentionally skips them — that is by design, not the bug. The bug is
different: when ``psycopg`` (or a sibling postgresql-extra package it pulls
in transitively, e.g. ``pgvector``) IS installed but at a version the
current ``uv.lock`` no longer pins, a local ``pytest --collect-only`` can
silently collect a DIFFERENT set of tests than CI's hash-pinned
``requirements/ci-postgresql.txt`` install produces — with no error and no
skip reason, just a smaller number a contributor trusts over CI's. That is
the exact drift issue #287 reports: 6572 collected locally vs. 6582 on CI,
which PR #284 had to work around by using CI's own verified count directly.

The same class of drift was independently caught the day before, in
``tests_py/scripts/test_launcher_pins_match_lock.py`` — ``pgvector`` 0.4.2
vs. 0.5.0, ``psycopg`` 3.3.3 vs. 3.3.4 — confirming a stale postgresql-extra
venv is a recurring, not hypothetical, failure mode in this repo, not a
one-off.

This module makes the divergence LOUD rather than impossible to have
(nothing here can force a contributor to re-run ``uv sync``):
``postgresql_extra_drift()`` is called eagerly from ``tests_py/conftest.py``
— the same "guard function called at module import time, `pytest.exit()` on
failure" convention that file already uses for its data-safety guards — and
any mismatch between an INSTALLED postgresql-extra package and the version
``requirements/ci-postgresql.txt`` pins for the running interpreter aborts
the session before collection starts, naming the exact packages and the
fix. A package that is not installed at all is left alone: that is either
a genuine SQLite-only dev install (nothing here to guard) or a package this
file does not pin, and both are outside what this check covers.
"""
````

## Original comment, lines 62–79

````text
# No separate "is this a comment/hash/blank line" pre-filter below: every
# such line's first non-whitespace character is "#", "-", "\", or nothing,
# none of which `_PIN_RE` (anchored on an alnum first character) ever
# matches, so they are already filtered by the `if not match` fall-through.
# A pre-filter would be redundant control flow for a result the regex
# already guarantees (confirmed empirically: dropping it parses the real
# `requirements/ci-postgresql.txt` to the identical 131-package set) —
# mutation testing surfaced exactly this as 6 equivalent survivors before
# it was removed (issue #287 PR discussion).
#
# `.split("\\", N)[0]` for any N>=1, an unbounded `.split("\\")[0]`, and
# even `.rsplit("\\", 1)[0]` are all EQUIVALENT here too, not just for
# realistic input: `_PIN_RE`'s character classes exclude backslash
# (`[^\s;\\]+`), so `match()` — which only needs a conforming PREFIX, not a
# full-string match — always halts at the first backslash it meets
# regardless of how much (or little) text trails it. Verified by
# construction and by a 200k-case fuzz across split/rsplit/maxsplit
# variants (issue #287 PR discussion), not asserted from reading the regex.
````

## Original docstring, lines 133–140

````text
"""``None`` if the venv is fine or the check does not apply; else a
    ready-to-print error naming every mismatched package and the fix.

    Scoped to ``psycopg`` as the activation signal: its presence means a
    contributor opted into the ``postgresql`` extra, so the FULL pinned set
    ``requirements/ci-postgresql.txt`` resolves to is what their collected
    test count should be measured against.
    """
````

