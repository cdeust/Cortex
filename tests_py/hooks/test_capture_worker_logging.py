"""Detached diagnostics stay bounded and refuse redirected log paths."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.hooks import capture_worker_logging as logs
from mcp_server.infrastructure.capture_peer import is_supported


# The worker log exists only where the capture worker runs (Linux/macOS Unix
# sockets, ADR-0486); elsewhere capture_dispatch spools instead.
@unittest.skipUnless(is_supported(), "no capture worker on this platform")
class TestCaptureWorkerLogging(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.logger = logging.getLogger()
        self.handlers = list(self.logger.handlers)
        self.level = self.logger.level

    def tearDown(self):
        for handler in list(self.logger.handlers):
            if handler not in self.handlers:
                self.logger.removeHandler(handler)
                handler.close()
        self.logger.setLevel(self.level)
        self.temporary.cleanup()

    def test_rotation_retains_only_current_and_previous_segment(self):
        with mock.patch.object(logs, "LOG_BYTES", 64):
            logs.configure(self.root)
        for number in range(4):
            self.logger.error("fixture segment %s %s", number, "x" * 40)
        paths = list(self.root.iterdir())
        self.assertEqual({path.name for path in paths}, {"worker.log", "worker.log.1"})
        self.assertIn("segment 3", (self.root / "worker.log").read_text())
        self.assertIn("segment 2", (self.root / "worker.log.1").read_text())

    def test_symlink_log_is_refused_without_touching_target(self):
        target = self.root / "kept"
        target.write_text("untouched")
        (self.root / "worker.log").symlink_to(target)
        with self.assertRaises(PermissionError):
            logs.configure(self.root)
        self.assertEqual(target.read_text(), "untouched")
