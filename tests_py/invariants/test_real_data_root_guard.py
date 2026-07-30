"""The `guard_against_real_data_roots` guard itself cannot be removed or
weakened.

Split out of test_store_isolation.py (issue #276/#287 boy-scout follow-up):
that file, together with the tests this session added, grew past
coding-standards.md §4.1's 300-line cap and needed decomposing along its
natural boundary — the RESOLVED-roots/live-write-path checks stayed in
test_store_isolation.py; the guard's own behavior and structural integrity
(can it be silently removed or its module-level call site weakened?) live
here.

The guard checks resolved values so it cannot be fooled by a
correct-looking environment. These tests drive it against a deliberately
un-isolated root and assert it aborts the session, then pin that both the
guard function and its unconditional call site in conftest.py survive a
future refactor.
"""

from __future__ import annotations

import os
import unittest.mock as mock
from pathlib import Path

import pytest

_REAL_CLAUDE_DIR = Path(os.path.expanduser("~/.claude")).resolve()

_CONFTEST_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "conftest.py")
)
_GUARDS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "_pg_safety_guards.py")
)


class TestIsolationGuard:
    """`guard_against_real_data_roots` must fire on a real root."""

    def test_guard_exits_when_a_root_escapes_isolation(self):
        """A WIKI_ROOT pointing at the real tree must abort with returncode=2.

        Postcondition: pytest.exit called once, returncode=2, message names
        the offending root so an operator can see which one escaped.
        """
        import tests_py.conftest as conftest
        from mcp_server.infrastructure import config
        from tests_py import _pg_safety_guards

        real_wiki = _REAL_CLAUDE_DIR / "methodology" / "wiki"
        with (
            mock.patch.object(config, "WIKI_ROOT", real_wiki),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            _pg_safety_guards.guard_against_real_data_roots(conftest._TEST_CLAUDE_DIR)

        mock_exit.assert_called_once()
        assert mock_exit.call_args[1].get("returncode") == 2
        assert "WIKI_ROOT" in mock_exit.call_args[0][0], (
            "Guard message does not name the offending root — an operator "
            f"cannot tell what escaped: {mock_exit.call_args[0][0]!r}"
        )

    def test_guard_is_silent_when_isolation_holds(self):
        """The live session is isolated, so the guard must NOT fire.

        Without this, a guard that always exits would pass the test above
        while making the suite unrunnable.
        """
        import tests_py.conftest as conftest
        from tests_py import _pg_safety_guards

        with mock.patch.object(pytest, "exit") as mock_exit:
            _pg_safety_guards.guard_against_real_data_roots(conftest._TEST_CLAUDE_DIR)
        mock_exit.assert_not_called()

    def test_guard_exit_message_is_exact_with_two_offenders(self):
        """Exact equality, with 2+ offenders so the join separator between
        them is exercised (a single offender can't distinguish a real "\\n"
        from a corrupted one). `expanduser`/`realpath` on "~/.claude" run
        for REAL, not mocked: a fixed `return_value` mock would return the
        same string for the correct literal and a mutated one alike."""
        from tests_py import _pg_safety_guards

        fake_offenders = [
            ("CLAUDE_DIR", "/real/claude"),
            ("WIKI_ROOT", "/real/claude/wiki"),
        ]
        expected_real_root = os.path.realpath(os.path.expanduser("~/.claude"))
        with (
            mock.patch.object(
                _pg_safety_guards,
                "_resolved_real_data_roots",
                return_value=fake_offenders,
            ),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            _pg_safety_guards.guard_against_real_data_roots("/isolated/tree")

        mock_exit.assert_called_once_with(
            "REFUSING to run: test isolation is not in effect. These roots "
            "still resolve outside the throwaway tree /isolated/tree:\n"
            "    CLAUDE_DIR -> /real/claude\n"
            "    WIKI_ROOT -> /real/claude/wiki\n"
            f"(real user root: {expected_real_root}). The suite DELETEs "
            "every table between tests and regenerates wiki dashboards — "
            "running it against a real tree destroys data (issue #219). "
            "Ensure _redirect_real_data_roots() runs before any mcp_server "
            "import.",
            returncode=2,
        )

    def test_guard_has_no_bypass_env_var(self):
        """Unlike the PG guard, this one must offer no override.

        A suite that DELETEs every table and regenerates wiki pages has no
        safe way to run against a real tree, so an escape hatch would only
        ever be used to re-enable the incident.
        """
        with open(_GUARDS_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        start = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("def guard_against_real_data_roots(")
        )
        end = next(
            (
                i
                for i in range(start + 1, len(lines))
                if lines[i] and lines[i][0] not in (" ", "\t", "\n")
            ),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "CORTEX_TEST_ALLOW" not in body, (
            "An override env-var was added to the isolation guard. There is "
            "no safe way to run this suite against a real data tree."
        )


class TestGuardStructuralIntegrity:
    """The redirection and the guard must both stay unconditional."""

    def test_redirect_runs_at_module_level(self):
        """`_redirect_real_data_roots()` must be called at zero indentation.

        Inside an `if`, it reintroduces exactly the conditional-isolation bug
        of issue #219.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        calls = [
            line
            for line in lines
            if line.strip().endswith("_redirect_real_data_roots()")
            and not line.startswith((" ", "\t"))
        ]
        assert calls, (
            "conftest.py no longer calls _redirect_real_data_roots() at "
            "module level — real-data roots are unisolated again (#219)."
        )

    def test_guard_call_present_at_module_level(self):
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        calls = [
            line
            for line in lines
            if line.strip().startswith(
                "_pg_safety_guards.guard_against_real_data_roots("
            )
            and not line.startswith((" ", "\t"))
        ]
        assert calls, (
            "conftest.py no longer calls "
            "_pg_safety_guards.guard_against_real_data_roots(...) at module "
            "level — isolation failures become silent again (#219)."
        )

    def test_redirect_precedes_first_mcp_server_import(self):
        """Ordering is load-bearing: constants bind at import time.

        `from mcp_server.infrastructure.config import METHODOLOGY_DIR` copies
        a value. If any mcp_server import runs before the env var is set, the
        copied value is the real path and no later env change can fix it.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        redirect_lines = [
            i
            for i, line in enumerate(lines)
            if line.strip().endswith("_redirect_real_data_roots()")
            and not line.startswith((" ", "\t"))
        ]
        assert redirect_lines, (
            "conftest.py has no module-level _redirect_real_data_roots() "
            "call, so nothing redirects the real-data roots at all (#219)."
        )
        redirect_line = redirect_lines[0]
        early_imports = [
            (i + 1, line.strip())
            for i, line in enumerate(lines[:redirect_line])
            if line.startswith(("import mcp_server", "from mcp_server"))
        ]
        assert not early_imports, (
            "mcp_server is imported before the roots are redirected, so path "
            f"constants bind to the real tree: {early_imports}"
        )
