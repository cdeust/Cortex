"""Regression test: importing `benchmarks.lib.*` must not require psycopg.

This test spawns a real subprocess with `psycopg`/`psycopg_pool`/
`pgvector` poisoned in `sys.modules` (`None`, the standard way to force
`ImportError` on a specific module) — a real subprocess so poisoning
sys.modules cannot leak into the shared pytest session.

None of the subprocess calls below carry a local `timeout=` (issue #402
follow-up). A fixed wall-clock bound makes a test's pass/fail verdict a
function of whatever else is running on the machine, not of the contract
under test — the one observed failure in this module (2026-08-09) traced
to a run sharing the host with three other agent sessions (load average
14 on 10 cores), not to any code defect. Enlarging the constant only
raises the load threshold at which that stays true; it does not remove
the dependency.

source: ADR-0892"""

from __future__ import annotations

import subprocess
import sys

import pytest

_POISON = (
    "import sys; "
    "sys.modules['psycopg'] = None; "
    "sys.modules['psycopg_pool'] = None; "
    "sys.modules['pgvector'] = None; "
    "sys.modules['pgvector.psycopg'] = None; "
)


def _run(snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _POISON + snippet],
        capture_output=True,
        text=True,
    )


def test_verification_report_importable_without_psycopg():
    """The bug this test pins: importing a PG-independent submodule of
    `benchmarks.lib` must not require psycopg."""
    result = _run(
        "import benchmarks.lib.verification_report as vr; "
        "assert vr.exp_result_name is not None; "
        "print('OK')"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_benchmark_db_still_reachable_lazily_and_fails_loudly_without_psycopg():
    """`BenchmarkDB` stays reachable via the package path, but resolving
    it without psycopg installed raises promptly and legibly — never a
    silent no-op, never blocking an unrelated submodule's import."""
    result = _run(
        "import benchmarks.lib as lib; "
        "assert 'BenchmarkDB' in lib.__all__; "
        "lib.BenchmarkDB"
    )
    assert result.returncode != 0
    assert "psycopg" in result.stderr


def test_benchmark_db_resolves_with_psycopg_present():
    """Sanity check the lazy path is not just erroring on everything:
    without poisoning sys.modules (real psycopg present in this venv),
    `benchmarks.lib.BenchmarkDB` resolves to the real class.

    Skipped (not failed) on an install genuinely without the Postgres
    extras (e.g. CI's SQLite-backend job, which explicitly installs "no
    postgresql extra") -- there psycopg's absence is the environment, not
    a regression, and `test_benchmark_db_still_reachable_lazily_and_fails_
    loudly_without_psycopg` above already pins that exact behavior.

    Runs IN-PROCESS, not in a subprocess (issue #402 follow-up). The
    other three tests in this module poison `sys.modules['psycopg']` etc.
    and MUST use a subprocess -- that poisoning must not leak into the
    shared pytest session. This test does none of that: it only checks
    that the PEP 562 `__getattr__` in `benchmarks/lib/__init__.py`
    resolves `BenchmarkDB` to the exact same class object
    `benchmarks.lib.bench_db.BenchmarkDB` names directly, which is true
    regardless of whether this is the first import of that module in the
    process or a cache hit -- Python's module cache guarantees identity
    either way, so no isolation is needed for this assertion to be
    meaningful.

    A prior version spawned `subprocess.run([sys.executable, "-c", ...],
    timeout=30)` for this test too. That made the verdict depend on wall
    clock, and therefore on whatever else was running on the machine at
    the time: the one observed failure (2026-08-09, issue #402) traced to
    a run made while three other agent sessions shared the host (load
    average 14 on 10 cores), not to any ordering or state-leak defect
    (ruled out: a subprocess.run(sys.executable, ...) child starts a
    fresh interpreter, so nothing in the parent's sys.modules/env can
    leak in, and every sys.modules/os.environ mutation site in
    tests_py/ was audited and restores cleanly). Enlarging the timeout
    would only have raised the load threshold at which the test still
    flakes, not removed the dependency -- the fix is to not measure wall
    clock for a question that has nothing to do with time.
    """
    pytest.importorskip("psycopg")
    import benchmarks.lib as lib
    from benchmarks.lib.bench_db import BenchmarkDB

    assert lib.BenchmarkDB is BenchmarkDB


def test_unknown_attribute_still_raises_attribute_error():
    result = _run("import benchmarks.lib as lib; lib.NotARealSymbol")
    assert result.returncode != 0
    assert "AttributeError" in result.stderr
