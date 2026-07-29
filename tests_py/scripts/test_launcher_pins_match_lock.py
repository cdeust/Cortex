"""scripts/launcher_deps.py's pins must equal what the lock installs.

Why this file exists
--------------------
``launcher_deps.py`` hand-restates a slice of the resolved dependency set so a
plugin install can `pip install --target` it without a resolver. Every entry
carried a "source: uv.lock" comment — and nine of the eleven had drifted from
that source by the time this test was written (2026-07-29, during the
transformers 4 -> 5 security migration):

    fastmcp               3.2.4  vs 3.4.5
    pydantic             2.13.3  vs 2.13.4
    pydantic-settings    2.14.0  vs 2.14.2
    psycopg               3.3.3  vs 3.3.4
    psycopg-pool          3.3.0  vs 3.3.1
    pgvector              0.4.2  vs 0.5.0
    sentence-transformers 5.4.1  vs 5.6.1
    numpy   one pin for >=3.11   vs a three-way fork (2.2.6/2.4.6/2.5.1)

That is the same failure ``scripts/generate_pip_constraints.py`` was built to
end for the requirements files ("Hand-maintaining them would reintroduce the
drift this replaces"), reappearing in the one place that still restates the
lock by hand. Drift here is not cosmetic: it makes a plugin install resolve a
dependency combination no CI job has ever exercised.

The reconciliation target is ``requirements/setup.txt`` rather than uv.lock
directly. That file IS the lock — the generator exports it and CI's Lint job
runs ``generate_pip_constraints.py --check`` on every PR — but it is already
flattened to concrete ``name==version ; marker`` lines, so this test needs no
second lock parser to fall out of step with uv's own.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from packaging.markers import Marker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPS_MODULE_PATH = REPO_ROOT / "scripts" / "launcher_deps.py"
# scripts/setup.sh's hash-pinned install set — see scripts/pip_constraint_sets.py.
LOCK_EXPORT_PATH = REPO_ROOT / "requirements" / "setup.txt"

# source: .github/workflows/ci.yml `test` matrix (python-version: 3.10-3.13),
# whose floor is pyproject.toml's `requires-python = ">=3.10"`.
SUPPORTED_PYTHON_MINORS = (10, 11, 12, 13)


def _marker_of(requirement_line: str) -> Marker | None:
    """The environment marker on a requirement line, or None when unmarked."""
    requirement = requirement_line.split("\\", 1)[0].strip()
    _spec, _, marker_text = requirement.partition(";")
    return Marker(marker_text.strip()) if marker_text.strip() else None


@pytest.fixture(scope="module")
def deps_mod():
    """Import scripts/launcher_deps.py by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location(
        "_cortex_launcher_deps_pins", DEPS_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock_versions(deps_mod) -> dict[str, str]:
    """Map normalised dist key -> version, for THIS interpreter.

    Only requirement lines whose environment marker evaluates true here are
    kept, so a forked package (numpy) contributes exactly the one version this
    Python would install. Marker evaluation is delegated to `packaging`, the
    same library pip resolves with — never a hand-rolled comparison.
    """
    versions: dict[str, str] = {}
    for raw in LOCK_EXPORT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        # Skip comments, hash continuations, and blank lines. Requirement
        # lines are the only ones that start with a distribution name.
        if not line or line.startswith(("#", "--hash", "-", "\\")):
            continue
        requirement = line.split("\\", 1)[0].strip()
        if "==" not in requirement:
            continue
        marker = _marker_of(line)
        if marker is not None and not marker.evaluate():
            continue
        key, version = deps_mod._parse_pip_spec(requirement.partition(";")[0].strip())
        versions[key] = version
    return versions


def test_lock_export_parses_to_a_realistic_package_set(deps_mod) -> None:
    """Guard the parser itself: a silently-empty parse would pass everything.

    Without this, a change to the export format (or a wrong path) would make
    `_lock_versions` return {} and every reconciliation below would vacuously
    pass while the pins drifted freely.
    """
    versions = _lock_versions(deps_mod)

    # setup.txt installs the postgresql + codebase + benchmarks extras; the
    # set is in the hundreds. 50 is a floor far below that and far above the
    # empty/near-empty parse this test exists to catch.
    assert len(versions) > 50
    # Anchors that must be present whatever else changes.
    assert versions["numpy"]
    assert versions["sentence_transformers"]


@pytest.mark.parametrize("attr", ["_BASE_PACKAGES", "_ML_PACKAGES"])
def test_launcher_pins_match_the_lock_export(deps_mod, attr: str) -> None:
    """Every launcher pin equals the version the lock export installs."""
    versions = _lock_versions(deps_mod)

    mismatches: list[str] = []
    for _import_name, spec in getattr(deps_mod, attr):
        key, pinned = deps_mod._parse_pip_spec(spec)
        expected = versions.get(key)
        if expected is None:
            mismatches.append(
                f"{key}: pinned {pinned} in {attr} but absent from "
                f"{LOCK_EXPORT_PATH.name} for Python {sys.version_info.major}."
                f"{sys.version_info.minor}"
            )
        elif expected != pinned:
            mismatches.append(f"{key}: launcher pins {pinned}, lock has {expected}")

    assert not mismatches, (
        f"{attr} disagrees with {LOCK_EXPORT_PATH.name}:\n  "
        + "\n  ".join(mismatches)
        + f"\nRe-run scripts/generate_pip_constraints.py, then update "
        f"{DEPS_MODULE_PATH.name} to the versions it exports."
    )


@pytest.mark.parametrize("minor", SUPPORTED_PYTHON_MINORS)
def test_numpy_pin_matches_the_lock_on_every_supported_python(
    deps_mod, minor: int
) -> None:
    """numpy's fork is right for EVERY supported Python, not just this one.

    The other pins are single-valued, so the reconciliation above proves them
    wherever it runs. numpy forks by Python version and a matrix leg only ever
    exercises its own branch, so a wrong pin on another branch would ship
    unnoticed — the 3.13 leg cannot see what 3.10 installs. Both sides are
    therefore evaluated at the target version: `packaging` resolves the
    export's markers against a synthetic environment, and the launcher's table
    is queried as a pure function.
    """
    version_info = (3, minor)
    # `python_full_version` is what every numpy marker in the export tests
    # against; `.0` is the patch level — markers here compare on minor only
    # ("< '3.11'", "== '3.11.*'", ">= '3.12'"), so any patch resolves alike.
    environment = {
        "python_full_version": f"3.{minor}.0",
        "python_version": f"3.{minor}",
    }

    expected = set()
    for line in LOCK_EXPORT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("numpy=="):
            continue
        marker = _marker_of(line)
        if marker is None or marker.evaluate(environment):
            expected.add(line.split("==", 1)[1].split(" ", 1)[0].strip())

    assert len(expected) == 1, (
        f"{LOCK_EXPORT_PATH.name} resolves {len(expected)} numpy versions on "
        f"Python 3.{minor} ({sorted(expected)}); exactly one must apply."
    )
    assert deps_mod._numpy_version(version_info) == expected.pop()
