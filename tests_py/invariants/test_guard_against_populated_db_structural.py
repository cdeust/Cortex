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

from __future__ import annotations

import pathlib

_CONFTEST_PATH = (pathlib.Path(__file__).parent / ".." / "conftest.py").resolve()
_GUARDS_PATH = (pathlib.Path(__file__).parent / ".." / "_pg_safety_guards.py").resolve()


class TestGuardStructuralIntegrity:
    def test_function_definition_present(self):
        """guard_against_populated_db must still be defined in
        _pg_safety_guards.py.

        Postcondition: the function definition line appears in the source.
        """
        with pathlib.Path(_GUARDS_PATH).open(encoding="utf-8") as fh:
            source = fh.read()

        assert "def guard_against_populated_db(" in source, (
            "_pg_safety_guards.py no longer defines guard_against_populated_db "
            "— the anti-537k guard has been removed."
        )

    def test_module_level_call_present(self):
        """guard_against_populated_db(...) must be called from conftest.py at
        module (col=0) level.

        The call must be unconditional — not inside an if-block or a function.
        A future refactor that moves the call inside a conditional or removes it
        entirely will cause the guard to stop running at collection time.

        Postcondition: at least one line at zero indentation calls
        `_pg_safety_guards.guard_against_populated_db(...)`.
        """
        with pathlib.Path(_CONFTEST_PATH).open(encoding="utf-8") as fh:
            lines = fh.readlines()

        module_level_calls = [
            (i + 1, line.rstrip())
            for i, line in enumerate(lines)
            if line.strip().startswith("_pg_safety_guards.guard_against_populated_db(")
            and not line.startswith((" ", "\t"))
        ]
        assert module_level_calls, (
            "conftest.py no longer calls "
            "_pg_safety_guards.guard_against_populated_db(...) at module "
            "level — the anti-537k guard is no longer active at test "
            "collection time. The call must exist at zero indentation."
        )

    def test_returncode_2_present_in_source(self):
        """The guard must still use returncode=2 (not 0 or 1) so CI can
        distinguish a deliberate guard-abort from a normal test failure.

        Postcondition: 'returncode=2' appears in _pg_safety_guards.py.
        """
        with pathlib.Path(_GUARDS_PATH).open(encoding="utf-8") as fh:
            source = fh.read()

        assert "returncode=2" in source, (
            "_pg_safety_guards.py's guard_against_populated_db no longer "
            "uses returncode=2 — operators will not be able to distinguish "
            "a guard-abort from a normal test failure."
        )

    def test_incident_date_mentioned_in_guard(self):
        """The guard docstring must reference the incident date (2026-06-10)
        so future maintainers understand why the guard exists.

        Postcondition: '2026-06-10' appears in _pg_safety_guards.py.
        """
        with pathlib.Path(_GUARDS_PATH).open(encoding="utf-8") as fh:
            source = fh.read()

        assert "2026-06-10" in source, (
            "The incident reference date '2026-06-10' has been removed from "
            "_pg_safety_guards.py — maintainers will lose context for why "
            "this guard exists."
        )
