"""Tests for the cortex-hook CLI entry point.

Covers:
  * Module name resolution with/without ``mcp_server.hooks.`` prefix
  * Invoking modules with main()
  * Invoking modules with process_event()
  * Exit codes for missing module / missing callable

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness).
"""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch


from mcp_server import hook_runner


class TestModuleResolution:
    def test_short_name_prefixed(self):
        """``cortex-hook session_start`` → mcp_server.hooks.session_start."""
        with patch.object(sys, "argv", ["cortex-hook", "session_start"]):
            with patch.object(hook_runner.importlib, "import_module") as mock_imp:
                fake_mod = MagicMock()
                fake_mod.main = MagicMock()
                mock_imp.return_value = fake_mod
                rc = hook_runner.run()
        mock_imp.assert_called_with("mcp_server.hooks.session_start")
        assert rc == 0

    def test_fully_qualified_name_unchanged(self):
        with patch.object(sys, "argv", ["cortex-hook", "mcp_server.hooks.auto_recall"]):
            with patch.object(hook_runner.importlib, "import_module") as mock_imp:
                fake_mod = MagicMock()
                fake_mod.main = MagicMock()
                mock_imp.return_value = fake_mod
                rc = hook_runner.run()
        mock_imp.assert_called_with("mcp_server.hooks.auto_recall")
        assert rc == 0


class TestMainInvocation:
    def test_main_called(self):
        called = []

        def _main():
            called.append(True)

        fake_mod = MagicMock()
        fake_mod.main = _main

        with patch.object(sys, "argv", ["cortex-hook", "x"]):
            with patch.object(
                hook_runner.importlib, "import_module", return_value=fake_mod
            ):
                rc = hook_runner.run()
        assert called == [True]
        assert rc == 0

    def test_main_systemexit_propagated(self):
        fake_mod = MagicMock()
        fake_mod.main = MagicMock(side_effect=SystemExit(7))
        with patch.object(sys, "argv", ["cortex-hook", "x"]):
            with patch.object(
                hook_runner.importlib, "import_module", return_value=fake_mod
            ):
                rc = hook_runner.run()
        assert rc == 7


class TestProcessEventFallback:
    def test_process_event_called_with_stdin_json(self):
        received = []

        def _process_event(event):
            received.append(event)

        fake_mod = MagicMock(spec=["process_event"])
        fake_mod.process_event = _process_event

        with patch.object(sys, "argv", ["cortex-hook", "x"]):
            with patch.object(
                hook_runner.importlib, "import_module", return_value=fake_mod
            ):
                with patch.object(sys, "stdin", io.StringIO('{"tool_name": "Edit"}')):
                    rc = hook_runner.run()
        assert received == [{"tool_name": "Edit"}]
        assert rc == 0

    def test_process_event_empty_stdin_returns_zero(self):
        fake_mod = MagicMock(spec=["process_event"])
        fake_mod.process_event = MagicMock()
        with patch.object(sys, "argv", ["cortex-hook", "x"]):
            with patch.object(
                hook_runner.importlib, "import_module", return_value=fake_mod
            ):
                with patch.object(sys, "stdin", io.StringIO("")):
                    rc = hook_runner.run()
        assert rc == 0


class TestErrorPaths:
    def test_missing_argv_returns_1(self):
        with patch.object(sys, "argv", ["cortex-hook"]):
            rc = hook_runner.run()
        assert rc == 1

    def test_module_not_found_returns_2(self):
        with patch.object(sys, "argv", ["cortex-hook", "nonexistent_module"]):
            with patch.object(
                hook_runner.importlib,
                "import_module",
                side_effect=ImportError("no mod"),
            ):
                rc = hook_runner.run()
        assert rc == 2

    def test_module_without_main_or_process_event_returns_4(self):
        fake_mod = MagicMock(spec=[])  # no main, no process_event
        with patch.object(sys, "argv", ["cortex-hook", "x"]):
            with patch.object(
                hook_runner.importlib, "import_module", return_value=fake_mod
            ):
                rc = hook_runner.run()
        assert rc == 4
