# ADR-0883: tests_py/_pg_safety_guards.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/_pg_safety_guards.py`, original SHA-256 `7461c6b987139130f5406de368c890a653c717cfc50ae7ce29133bb2348f13fe`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–15

````text
"""Fail-closed guards against running the destructive test suite against a
real database or a real `~/.claude` tree.

Extracted from `tests_py/conftest.py` (issue #276/#287 boy-scout follow-up)
as part of bringing that file under the repo's 300-line cap
(coding-standards.md §4.1) — see `tests_py/_pg_throwaway_db.py`'s docstring
for the full rationale. Behavior is unchanged: both guards below still
call `pytest.exit(..., returncode=2)` themselves (that call does not need
to happen inside a named pytest hook — conftest.py invokes these as plain
functions at module-import time, exactly as it invoked the code before the
extraction), with the same messages and the same conditions. The only
change is that they take their inputs as explicit parameters instead of
reading `tests_py/conftest.py`'s module globals directly — an incidental
DI improvement (these are independently testable now), not the goal.
"""
````

