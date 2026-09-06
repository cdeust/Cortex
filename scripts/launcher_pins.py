#!/usr/bin/env python3
"""The pinned dependency set a plugin install resolves — stdlib only.

The third stdlib-only sibling of ``launcher_deps`` (with ``launcher_deps_fs``
and ``launcher_deps_install``), split out on the same SRP boundary: this
module answers WHICH versions to install; ``launcher_deps`` decides WHEN to
install them and ``launcher_deps_install`` performs the install. The two
change for different reasons — this file moves on every lock bump, the policy
layer moves when the bootstrap protocol changes.

Every version here is the one ``requirements/setup.txt`` installs — the
hash-pinned export of uv.lock that ``scripts/generate_pip_constraints.py``
writes and CI's Lint job re-checks against the lock on every PR.

Why restating the lock by hand needs a guard
--------------------------------------------
This list exists because a plugin bootstrap runs before any resolver is
available, so it cannot read uv.lock itself. Hand-restating a lock is exactly
the drift ``generate_pip_constraints.py`` was built to end for the
requirements files ("Hand-maintaining them would reintroduce the drift this
replaces") — and it had already happened here. Measured 2026-07-29, during
the transformers 4 -> 5 security migration, nine of the eleven pins disagreed
with the lock they cited:

    fastmcp               3.2.4  vs 3.4.5
    pydantic             2.13.3  vs 2.13.4
    pydantic-settings    2.14.0  vs 2.14.2
    psycopg               3.3.3  vs 3.3.4
    psycopg-pool          3.3.0  vs 3.3.1
    pgvector              0.4.2  vs 0.5.0
    sentence-transformers 5.4.1  vs 5.6.1
    numpy   one pin for >=3.11   vs a three-way fork

each under a "source: uv.lock" comment that was no longer true. Drift here is
not cosmetic: it makes a plugin install resolve a combination no CI job has
ever exercised.

The reconciliation is now executable —
``tests_py/scripts/test_launcher_pins_match_lock.py`` fails when this module
and ``requirements/setup.txt`` disagree, on every supported Python — so a lock
bump can no longer silently leave the launcher behind.
"""

from __future__ import annotations

import sys

# numpy is the one pin that forks by Python version:
#   2.2.6 for Python < 3.11   (marker "python_full_version < '3.11'")
#   2.4.6 for Python == 3.11  (marker "python_full_version == '3.11.*'")
#   2.5.1 for Python >= 3.12  (marker "python_full_version >= '3.12'")
# source: requirements/setup.txt (numpy entries).
#
# A table read by a function, not an if/elif chain, because the branch the
# running interpreter does NOT take is where a wrong pin hides: a 3.13 CI leg
# cannot observe the 3.10 branch. As data, every row is reconcilable against
# the export from any interpreter.
#
# Rows are (exclusive upper bound, version) in ascending order; NUMPY_TAIL
# covers every Python at or above the last bound.
NUMPY_BY_UPPER_BOUND: tuple[tuple[tuple[int, int], str], ...] = (
    ((3, 11), "2.2.6"),
    ((3, 12), "2.4.6"),
)
NUMPY_TAIL = "2.5.1"


def numpy_version(version_info: tuple[int, int]) -> str:
    """The numpy version ``requirements/setup.txt`` installs on ``version_info``.

    precondition: ``version_info`` is a (major, minor) pair.
    postcondition: pure; returns the pin for the first bound it falls under,
    else the open-ended tail.
    """
    for upper, pinned in NUMPY_BY_UPPER_BOUND:
        if version_info < upper:
            return pinned
    return NUMPY_TAIL


# Base runtime (every entry point) + postgres trio (pg_store hard-imports at
# module load): (import_name, pip_spec).
# source: requirements/setup.txt (every version below).
BASE_PACKAGES: list[tuple[str, str]] = [
    ("mcp", "mcp==2.0.0"),
    ("pydantic", "pydantic==2.13.4"),
    ("pydantic_settings", "pydantic-settings==2.14.2"),
    ("numpy", f"numpy=={numpy_version(sys.version_info[:2])}"),
    ("psycopg", "psycopg[binary]==3.3.5"),
    ("psycopg_pool", "psycopg_pool==3.3.1"),
    ("pgvector", "pgvector==0.5.0"),
]

# ML stack — SessionStart-only. sentence-transformers is what pulls
# `transformers` in on this path, so its pin is what decides which
# transformers version a plugin install resolves.
# source: requirements/setup.txt (every version below).
ML_PACKAGES: list[tuple[str, str]] = [
    ("sentence_transformers", "sentence-transformers==5.6.1"),
    ("flashrank", "flashrank==0.2.10"),
]
