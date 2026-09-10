# ADR-1016: tests_py/invariants/test_guard_against_populated_db_structural.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/invariants/test_guard_against_populated_db_structural.py`, original SHA-256 `67cc7ae864ad02dbfae6b044687f712089c0be1cb7b10d9d6e81f86482ef97a0`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–11

````text
"""Static-analysis regression guard: `guard_against_populated_db` cannot be
silently removed or its module-level call site weakened.

Split out of test_conftest_guard.py (issue #276/#287 boy-scout follow-up
— see test_guard_against_populated_db.py's docstring for the size-cap
rationale this split serves). These tests read the source of
`_pg_safety_guards.py` (the guard's definition) and `conftest.py` (its
unconditional call site) and assert structural properties. A change that
deletes the function, changes its name, or wraps the call in a
conditional will fail one of these tests.
"""
````

