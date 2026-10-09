"""Capture composition fixtures never import a real handler/store/model."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.hooks.launcher_command import launcher_path
from tests_py.hooks.test_capture_worker_policy import payload


class TestCaptureDispatch(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = mock.patch.dict(
            os.environ, {"CORTEX_CLAUDE_DIR": self.temporary.name}
        )
        self.environment.start()
        from mcp_server.hooks import capture_dispatch
        from mcp_server.core import telemetry

        self.dispatch = capture_dispatch
        self.record = mock.patch.object(telemetry, "record").start()

    def tearDown(self):
        mock.patch.stopall()
        self.environment.stop()
        self.temporary.cleanup()

    def test_hook_transmits_the_exact_previous_payload_without_inference(self):
        from mcp_server.hooks import post_tool_capture as hook

        expected = payload("the full capture", "/fixture", ["auto-captured"])
        with mock.patch.object(self.dispatch, "dispatch", return_value=True) as send:
            with mock.patch.object(
                hook, "_load_remember", side_effect=AssertionError("in-process")
            ):
                with mock.patch.object(hook, "_log") as log:
                    hook._store_memory(
                        "NotebookEdit",
                        "the full capture",
                        ["auto-captured"],
                        "/fixture",
                    )
        send.assert_called_once_with(expected)
        self.assertIn("persistence pending", log.call_args.args[0])

    def test_spawn_or_transport_failure_is_logged_and_telemetried(self):
        with mock.patch.object(
            self.dispatch, "deliver", side_effect=OSError("fixture spawn failed")
        ):
            with mock.patch.object(
                self.dispatch.time, "monotonic", side_effect=[4.0, 4.25]
            ):
                with self.assertLogs(self.dispatch.logger, level="ERROR") as logs:
                    self.assertFalse(self.dispatch.dispatch(payload()))
        self.assertIn("fixture spawn failed", " ".join(logs.output))
        self.record.assert_called_once_with(
            "capture_skipped", latency_ms=250.0, ok=False, skipped=True
        )

    def test_invalid_payload_never_reaches_spawn_or_transport(self):
        with mock.patch.object(self.dispatch, "deliver") as deliver:
            with self.assertLogs(self.dispatch.logger, level="ERROR"):
                self.assertFalse(self.dispatch.dispatch({}))
        deliver.assert_not_called()
        self.record.assert_called_once()

    def test_lifecycle_error_uses_its_own_event_and_measured_duration(self):
        with self.assertLogs(self.dispatch.logger, level="ERROR"):
            self.dispatch.report_failure(
                "fixture cleanup", 0.25, "capture_worker_lifecycle"
            )
        self.record.assert_called_once_with(
            "capture_worker_lifecycle", latency_ms=250.0, ok=False, skipped=False
        )

    def test_spawn_detaches_every_stdio_stream_and_passes_only_worker_fds(self):
        listener = mock.Mock()
        listener.fileno.return_value = 7
        prepared = {"PYTHONPATH": "fixture-deps", "CLAUDE_PLUGIN_DATA": "fixture-data"}
        with mock.patch.dict(os.environ, prepared):
            expected_environment = dict(os.environ)
            with mock.patch.object(subprocess, "Popen") as spawn:
                self.dispatch._spawn(listener, 8)
        arguments, options = spawn.call_args.args[0], spawn.call_args.kwargs
        # issue #667: through the launcher (deps isolation), never a bare -m
        self.assertEqual(
            arguments[:3],
            [sys.executable, str(launcher_path()), "mcp_server.hooks.capture_worker"],
        )
        self.assertEqual(arguments[3:], ["--listener-fd", "7", "--lease-fd", "8"])
        self.assertEqual(options["pass_fds"], (7, 8))
        self.assertTrue(options["start_new_session"])
        self.assertEqual(options["env"], expected_environment)
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(options[stream], subprocess.DEVNULL)

    def test_worker_reuses_one_loop_and_handler_for_consecutive_payloads(self):
        from mcp_server.hooks import capture_worker, post_tool_capture

        loops, received = [], []

        async def handler(value):
            loops.append(asyncio.get_running_loop())
            received.append(value)
            return {"stored": True, "memory_id": "fixture"}

        async def work():
            await capture_worker.remember(payload("first"))
            await capture_worker.remember(payload("second"))

        with mock.patch.object(
            post_tool_capture, "_load_remember", return_value=(asyncio, handler)
        ):
            asyncio.run(work())
        self.assertIs(loops[0], loops[1])
        self.assertEqual(received, [payload("first"), payload("second")])

    def test_loader_exit_is_an_observable_processing_error(self):
        from mcp_server.hooks import capture_worker, post_tool_capture

        with mock.patch.object(
            post_tool_capture, "_load_remember", side_effect=SystemExit(1)
        ):
            with self.assertRaisesRegex(RuntimeError, "dependencies unavailable"):
                asyncio.run(capture_worker.remember(payload()))

    def test_hook_dispatch_imports_do_not_load_memory_or_model(self):
        command = """
import sys
from mcp_server.hooks import capture_dispatch, capture_worker
for name in ('mcp_server.core', 'mcp_server.handlers.remember',
             'mcp_server.infrastructure.memory_store',
             'mcp_server.infrastructure.embedding_engine', 'torch',
             'sentence_transformers'):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", command],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
