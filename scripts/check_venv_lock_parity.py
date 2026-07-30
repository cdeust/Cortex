#!/usr/bin/env python3
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

from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path
from typing import Callable

from packaging.markers import Marker

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_POSTGRESQL_TXT = REPO_ROOT / "requirements" / "ci-postgresql.txt"

# A pinned requirement line: "name==version", optionally followed by
# "; marker" and/or a trailing "\" continuation. Comment, hash-continuation,
# and blank lines are filtered by the caller before this ever sees them.
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")


def _normalize(name: str) -> str:
    """PEP 503 normalization: pip/uv/importlib.metadata all treat
    ``psycopg-pool`` and ``psycopg_pool`` as the same distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


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
def parse_pinned_versions(requirements_text: str) -> dict[str, str]:
    """``name -> version`` for every requirement line whose marker (if any)
    applies to the CURRENTLY RUNNING interpreter.

    A package pinned to two versions by a ``python_full_version`` marker
    (e.g. ``aiofile`` forks on 3.11) contributes exactly the one version
    this interpreter would receive from ``uv sync`` — resolved via
    ``packaging.markers``, the same library ``pip`` and ``uv`` themselves
    evaluate markers with, never a hand-rolled comparison.
    """
    versions: dict[str, str] = {}
    for raw in requirements_text.splitlines():
        line = raw.strip()
        requirement = line.split("\\", 1)[0].strip()
        match = _PIN_RE.match(requirement)
        if not match:
            continue
        _spec, _, marker_text = requirement.partition(";")
        if marker_text.strip() and not Marker(marker_text.strip()).evaluate():
            continue
        versions[_normalize(match.group(1))] = match.group(2)
    return versions


def find_mismatches(
    pinned: dict[str, str],
    installed_version: Callable[[str], str | None],
) -> list[str]:
    """Packages that ARE installed but at a version ``pinned`` disagrees with.

    A package absent from ``installed_version`` (returns ``None``) is not a
    mismatch: that is either an intentionally narrower extra set (a
    SQLite-only dev install) or a package this file does not pin at all,
    and both are outside what this guard checks.
    """
    mismatches = []
    for name, pinned_version in sorted(pinned.items()):
        actual = installed_version(name)
        if actual is not None and actual != pinned_version:
            mismatches.append(f"{name}: installed {actual}, lock pins {pinned_version}")
    return mismatches


def installed_version(name: str) -> str | None:
    """Real adapter: the version ``importlib.metadata`` resolves for `name`,
    or ``None`` when the distribution is not installed."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def postgresql_extra_drift() -> str | None:
    """``None`` if the venv is fine or the check does not apply; else a
    ready-to-print error naming every mismatched package and the fix.

    Scoped to ``psycopg`` as the activation signal: its presence means a
    contributor opted into the ``postgresql`` extra, so the FULL pinned set
    ``requirements/ci-postgresql.txt`` resolves to is what their collected
    test count should be measured against.
    """
    if installed_version("psycopg") is None:
        return None  # no postgresql extra installed — nothing to guard

    pinned = parse_pinned_versions(CI_POSTGRESQL_TXT.read_text(encoding="utf-8"))
    mismatches = find_mismatches(pinned, installed_version)
    if not mismatches:
        return None

    return (
        "Local venv has drifted from requirements/ci-postgresql.txt — the "
        "file CI's 'Check advertised test count' step installs from "
        "(issue #287). A version-mismatched postgresql-extra package can "
        "change which tests import successfully at collection time, so the "
        "locally collected test count silently stops matching CI's. "
        "Mismatches:\n"
        + "\n".join(f"  {m}" for m in mismatches)
        + "\nFix: re-run `uv sync --no-default-groups --extra dev --extra "
        "postgresql --extra sqlite --extra codebase --extra benchmarks` "
        "(CONTRIBUTING.md § Dev setup) to resync this venv to uv.lock."
    )


def main(argv: list[str]) -> int:
    """Standalone entry point: ``python3 scripts/check_venv_lock_parity.py``."""
    del argv
    message = postgresql_extra_drift()
    if message is None:
        print(
            "OK: no postgresql-extra version drift from requirements/ci-postgresql.txt"
        )
        return 0
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
