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
    ("psycopg", "psycopg[binary]==3.3.4"),
    ("psycopg_pool", "psycopg_pool==3.3.1"),
    ("pgvector", "pgvector==0.5.0"),
]

# ML stack — SessionStart-only. sentence-transformers is what pulls
# `transformers` in on this path, so its pin is what decides which
# transformers version a plugin install resolves.
# source: requirements/setup.txt (every version below).
_ML_COMMON: list[tuple[str, str]] = [
    ("sentence_transformers", "sentence-transformers==5.6.1"),
    ("flashrank", "flashrank==0.2.10"),
]

# source: requirements/setup.txt's Linux torch entry and pyproject.toml's
# explicit pytorch-cpu index. Including this pin invalidates pre-CPU ML stamps.
TORCH_CPU_SPEC = "torch==2.13.0+cpu"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def ml_packages(platform: str) -> list[tuple[str, str]]:
    """Preserve the non-Linux stack; Linux stamps also require CPU torch."""
    packages = list(_ML_COMMON)
    if platform == "linux":
        packages.append(("torch", TORCH_CPU_SPEC))
    return packages


ML_PACKAGES = ml_packages(sys.platform)


# source: requirements/setup.txt, torch==2.13.0+cpu; all compatible wheel hashes.
# Reconciled to the export and uv.lock by test_launcher_torch_cpu_pins.py.
TORCH_CPU_HASHES = (
    "0555fde6108ca90247ae33d4e1237cbae475c86a223bb2f0f91d9addf1f611bd",
    "0b8f7d0423027ae8b90c7977c627f3379f325363a08224dffad9b4b2d684a83d",
    "1a3a35229fdc13446b4eab50e7fcf9399ff941e89a3b761497786297a5d8dde5",
    "222a6681467cc7f6f05cd3068dfbc603def3a1e46d1d4620c1c8cdf6178bd563",
    "3fbf9c9d1f3c10c2d59d04aca426dee9ccc6ceb32d255c61e93acc3b4f75fae6",
    "4ca4a9394b0c771238a4f73590fdbbc4debad85ed0fa63d026ae1b085da7d6e2",
    "6746dbcbeb526eb61330b76b41ff1b4eb848951103a892eeb080dfa2b264667b",
    "6e9817dbdf5ea76789babd46e457eac5bf14ff566cf85f8addbfdff2d56601ce",
    "6f307c2c32d764ffc6ff6893b801fad6d4752f3e67966cb8abf1843427c02604",
    "7b8d26e29bceafbdaa8d63bfe7612f23875b5af2cc07e13f809c3ed890bbe1d8",
    "84453b69508ec79902f899c5ed9495acb9e2bbe9fda5f1d5d6f19e3c3842e1a7",
    "8e109528e6bab044815daebaf71770fbaace3a66ef1c816cb55c875350f78a60",
    "8eb5002ca81af00ae69b57540f615b58b8ae922b6d4848176b366a52bd2196e6",
    "966d020354f465672dc7dd10d3a5c6cd17d7eb48620aa1d265b48a1f78f06898",
    "991cc14b39e751122c01f017be6448533989868731cb5eecd1006893d26787c2",
    "b222c15a0fc2ce207d1c1a59700b46c8fa6748df1f447ad11e5c870dde0933d9",
    "ca021f9eb2f8345c83fa03e3a04587308afb8df71bd472670b3ece00df58621c",
    "d20fa53ee744502fa4c69818a720b05ca0d37abd055d4f6e66cae155114bc691",
    "dec241fef3984c0d1edadd1f58708e218d4eae881ceef7bc10cf9964d41b68b9",
    "f028e428bddee95cdb86e2470254e95c9af629362488550c200ed4793125a817",
    "f5cbb61180a9793d9e12fe115a2310d2600bd449dfb9a01ec5640e21359fa5ea",
    "ffadde149901c8afa138daa38d898264003cfcf1a3336ca5cd964b5af227d867",
)
