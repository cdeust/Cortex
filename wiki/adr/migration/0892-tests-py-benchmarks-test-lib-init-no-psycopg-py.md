# ADR-0892: tests_py/benchmarks/test_lib_init_no_psycopg.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/benchmarks/test_lib_init_no_psycopg.py`, original SHA-256 `6955b7e6558d0406188e6f000bc340d7f0f313b2b92a2804e96e27065a8c503b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–54

````text
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

None of the subprocess calls below carry a local `timeout=` (issue #402
follow-up). A fixed wall-clock bound makes a test's pass/fail verdict a
function of whatever else is running on the machine, not of the contract
under test — the one observed failure in this module (2026-08-09) traced
to a run sharing the host with three other agent sessions (load average
14 on 10 cores), not to any code defect. Enlarging the constant only
raises the load threshold at which that stays true; it does not remove
the dependency.

A genuine hang is still caught by pytest's own global watchdog
(`pyproject.toml` `[tool.pytest.ini_options] timeout = 300`, sourced to
the 2026-05-25 CI stall incident) — but that backstop is coarser than a
per-test timeout, and worth stating precisely rather than implying more
than it delivers: with `timeout_method = "thread"` (the only method
compatible with `pytest-asyncio`, per that same pyproject.toml comment),
expiry dumps every thread's stack and then calls `os._exit(1)`
(`pytest_timeout.py::timeout_timer`, pytest-timeout 2.4.0, the version
pinned in `uv.lock`) — the WHOLE interpreter terminates immediately, not
just the timed-out test; there is no clean per-test failure, and any
subprocess still blocked at that moment is orphaned (`os._exit` skips
atexit handlers and does not reap children). That is the tradeoff this
file accepts in exchange for a verdict that no longer depends on machine
load: a genuine hang is still loud and diagnosable (the dumped stacks
name exactly what was stuck), on the same terms every other hang-capable
test in this suite already relies on — nothing here newly weakens that
contract, and removing this file's own narrower, unsourced 30s bound
does not weaken it further.
"""
````

