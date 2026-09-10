#!/usr/bin/env python3
"""Guard a stale postgresql-extra install from silently under-collecting
tests.

The same class of drift was independently caught the day before, in
``tests_py/scripts/test_launcher_pins_match_lock.py`` — ``pgvector`` 0.4.2
vs. 0.5.0, ``psycopg`` 3.3.3 vs. 3.3.4 — confirming a stale postgresql-extra
venv is a recurring, not hypothetical, failure mode in this repo, not a
one-off.

source: ADR-0716"""

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


# source: ADR-0716
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

    source: ADR-0716"""
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
