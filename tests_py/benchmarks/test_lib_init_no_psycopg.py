"""Regression test: importing `benchmarks.lib.*` must not require psycopg.

`benchmarks/lib/__init__.py` used to eagerly `import BenchmarkDB` at
top level, which transitively hard-imports `psycopg`/`psycopg_pool`/
`pgvector` (`benchmarks/lib/bench_db.py` -> `mcp_server/infrastructure/
pg_store.py`). Because Python always runs a package's `__init__.py`
before any of its submodules, that made every submodule of
`benchmarks.lib` — including the Postgres-independent
`verification_report.py` — unimportable on an install without the
Postgres extras (reproduced on CI's SQLite-backend job, PR closing
issue #282: `ModuleNotFoundError: No module named 'psycopg'` raised
from collecting `tests_py/benchmarks/test_verification_report.py`,
which imports nothing PG-related itself). Every other consumer of
`bench_db.BenchmarkDB` in this package already defers that import
inside a function for exactly this reason (see the "deferred: module
hard-imports pgvector/psycopg/psycopg_pool at top level" comments in
`ablation_runner.py`, `longitudinal_runner.py`, `_xb_drivers.py`,
`llm_head_to_head/pilot.py`); `__init__.py` did not follow its own
package's convention. Fixed via a PEP 562 module `__getattr__` that
resolves `BenchmarkDB` lazily.

This test spawns a real subprocess with `psycopg`/`psycopg_pool`/
`pgvector` poisoned in `sys.modules` (`None`, the standard way to force
`ImportError` on a specific module) — a real subprocess so poisoning
sys.modules cannot leak into the shared pytest session.
"""

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
        timeout=30,
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
    """
    pytest.importorskip("psycopg")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import benchmarks.lib as lib; "
            "from benchmarks.lib.bench_db import BenchmarkDB; "
            "assert lib.BenchmarkDB is BenchmarkDB; "
            "print('OK')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_unknown_attribute_still_raises_attribute_error():
    result = _run("import benchmarks.lib as lib; lib.NotARealSymbol")
    assert result.returncode != 0
    assert "AttributeError" in result.stderr
