"""A failed listener must release its resident lifecycle immediately."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.infrastructure import capture_server as server_module
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_transport import CaptureTransportError, Limits


class TestCaptureServerFailure(unittest.TestCase):
    def setUp(self):
        self.journal = tempfile.TemporaryDirectory()
        self.addCleanup(self.journal.cleanup)

    def test_broken_listener_wakes_idle_consumer_and_reports(self):
        listener = mock.Mock()
        listener.accept.side_effect = OSError("fixture listener closed")
        report, callback = mock.Mock(), mock.AsyncMock()
        server = CaptureServer(
            listener,
            callback,
            ServerPolicy(Limits(4096, 1, 300), report, Path(self.journal.name)),
        )
        server.run()
        self.assertTrue(server.stopping.is_set())
        report.assert_called_once()
        message, elapsed, operation = report.call_args.args
        self.assertEqual(message, "capture listener failed: fixture listener closed")
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual(operation, "capture_worker_lifecycle")
        callback.assert_not_called()
        listener.close.assert_called_once()

    def test_receive_failure_reports_measured_admission_duration(self):
        report = mock.Mock()
        server = CaptureServer(
            mock.Mock(),
            mock.AsyncMock(),
            ServerPolicy(Limits(4096, 1, 300), report, Path(self.journal.name)),
        )
        clock = mock.Mock()
        clock.monotonic.side_effect = [2.0, 2.25, 2.5]
        with (
            mock.patch.object(server_module, "time", clock),
            mock.patch.object(server_module, "authenticate"),
        ):
            with mock.patch.object(
                server_module,
                "receive",
                side_effect=CaptureTransportError("fixture frame"),
            ):
                server._receive(mock.Mock())
        self.assertEqual(report.call_args.args[1:], (0.25, "capture_skipped"))

    def test_processing_failure_reports_measured_processing_duration(self):
        report = mock.Mock()
        callback = mock.AsyncMock(side_effect=ValueError("fixture handler"))
        server = CaptureServer(
            mock.Mock(),
            callback,
            ServerPolicy(Limits(4096, 1, 300), report, Path(self.journal.name)),
        )
        clock = mock.Mock()
        clock.monotonic.side_effect = [2.0, 2.25]
        with mock.patch.object(server_module, "time", clock):
            entry = ({"content": "fixture"}, Path(self.journal.name) / "a.json")
            with mock.patch.object(server, "_next", side_effect=[entry, None]):
                asyncio.run(server._consume([]))
        self.assertEqual(report.call_args.args[1:], (0.25, "capture_skipped"))
