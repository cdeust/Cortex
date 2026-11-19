"""Uses W2-1a's sys.modules-only cleanup contract; never imports a real store."""

from __future__ import annotations

import builtins
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest import mock

from mcp_server.hooks import capture_worker as worker
from mcp_server.hooks.capture_dispatch import report_failure
from mcp_server.hooks.capture_worker_policy import limits
from mcp_server.infrastructure import config
from mcp_server.infrastructure.capture_server import ServerPolicy
from mcp_server.infrastructure.capture_spool import spool_path


class TestCaptureWorkerShutdown(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.runtime = self.root / ".capture-worker"
        self.events = []
        self.stack.enter_context(mock.patch.dict(sys.modules))
        sys.modules.pop("mcp_server.infrastructure.memory_store", None)
        self._patch_paths()
        self._patch_exit()

    def _patch_paths(self):
        self.stack.enter_context(
            mock.patch.object(worker, "runtime_directory", return_value=self.runtime)
        )
        self.stack.enter_context(mock.patch.object(worker, "configure"))
        listener = self.stack.enter_context(mock.patch.object(worker.socket, "socket"))
        self.listener = listener.return_value
        self.stack.enter_context(mock.patch.object(config, "CLAUDE_DIR", self.root))
        listener.return_value.getsockname.return_value = str(self.runtime / "socket")
        self.server = self.stack.enter_context(
            mock.patch.object(worker, "CaptureServer")
        )

    def _patch_exit(self):
        self.stack.enter_context(
            mock.patch.object(
                worker,
                "remove_socket",
                side_effect=lambda _: self.events.append("socket-remove"),
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                worker.os,
                "close",
                side_effect=lambda _: self.events.append("lease-close"),
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                sys, "argv", ["worker", "--listener-fd", "7", "--lease-fd", "8"]
            )
        )

    def tearDown(self):
        self.stack.close()

    def _callback(self, fail=False):
        store = ModuleType("mcp_server.infrastructure.memory_store")
        store.reset_shared_store = mock.Mock(
            side_effect=lambda: self.events.append("store-close")
        )
        sys.modules[store.__name__] = store
        if fail:
            raise RuntimeError("fixture worker failure")

    def test_loaded_store_is_closed_on_idle_before_releasing_lease(self):
        self.server.return_value.run.side_effect = self._callback
        worker.main()
        self.assertEqual(self.events, ["store-close", "socket-remove", "lease-close"])

    def test_loaded_store_is_closed_on_failure_before_releasing_lease(self):
        self.server.return_value.run.side_effect = lambda: self._callback(fail=True)
        with self.assertRaisesRegex(RuntimeError, "fixture worker failure"):
            worker.main()
        self.assertEqual(self.events, ["store-close", "socket-remove", "lease-close"])

    def test_idle_without_any_payload_never_imports_a_store(self):
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name.startswith("mcp_server.infrastructure.memory_store"):
                raise AssertionError("idle cleanup tried to import a store")
            return original(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", guarded):
            worker.main()
        self.assertNotIn("mcp_server.infrastructure.memory_store", sys.modules)
        self.assertEqual(self.events, ["socket-remove", "lease-close"])

    def test_the_server_journals_admissions_in_the_configured_spool(self):
        # source: ADR-1142 — the spool of the configured root is the journal
        worker.main()
        self.server.assert_called_once_with(
            self.listener,
            worker.remember,
            ServerPolicy(limits(), report_failure, spool_path(self.root)),
        )
        self.server.return_value.run.assert_called_once_with()
