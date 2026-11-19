"""What the capture worker reports about its journal, word for word (ADR-1142).

The journal's outcomes reach the user only through these reports (``capture_skipped``
counts a lost capture, ``capture_worker_lifecycle`` an error of the worker), so the
message, the measured duration and the operation are each pinned here.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_transport import Limits


class TestJournalReports(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = Path(directory.name)
        self.report = mock.Mock()

    def server(self, callback=None, listener=None) -> CaptureServer:
        # A short idle wait: a consumer that never stops ends the test in 1 s.
        policy = ServerPolicy(Limits(4096, 1, 1), self.report, self.journal)
        return CaptureServer(listener or mock.Mock(), callback, policy)

    def assert_reported(self, message: str, operation: str) -> None:
        reported, elapsed, kind = self.report.call_args.args
        self.assertEqual((reported, kind), (message, operation))
        self.assertIsInstance(elapsed, float)
        self.assertTrue(0.0 <= elapsed < 5.0, elapsed)

    def test_a_failed_store_names_its_fate_and_its_exception(self):
        callback = mock.AsyncMock(side_effect=ValueError("fixture store"))
        path = capture_spool.write(self.journal, {"content": "failed"})
        asyncio.run(self.server(callback)._process({"content": "failed"}, path))
        self.assert_reported(
            "capture processing failed (kept for inspection): "
            "ValueError: fixture store",
            "capture_skipped",
        )

    def test_a_failed_store_whose_file_cannot_be_renamed_says_so(self):
        path = capture_spool.write(self.journal, {"content": "failed"})

        async def callback(_payload):
            path.unlink()  # the rename that retires it now fails
            raise ValueError("fixture store")

        asyncio.run(self.server(callback)._process({"content": "failed"}, path))
        message = self.report.call_args.args[0]
        self.assertTrue(
            message.startswith("capture processing failed (left in place, rename"),
            message,
        )
        self.assertTrue(message.endswith("): ValueError: fixture store"), message)

    def test_a_journal_file_that_cannot_be_removed_is_reported_as_replayable(self):
        path = self.journal / "entry.json"
        path.mkdir()  # unlink() of a directory fails, for root too
        callback = mock.AsyncMock()
        asyncio.run(self.server(callback)._process({"content": "kept"}, path))
        callback.assert_awaited_once_with({"content": "kept"})
        message, _, _ = self.report.call_args.args
        prefix = "capture journal entry not removed, it will be replayed: "
        self.assertTrue(message.startswith(prefix), message)
        self.assert_reported(message, "capture_worker_lifecycle")

    def test_an_unreadable_journal_file_is_refused_and_the_next_one_replayed(self):
        broken = self.journal / "0-broken.json"
        broken.write_text("{not json", encoding="utf-8")
        good = capture_spool.write(self.journal, {"content": "good"})
        callback = mock.AsyncMock()
        asyncio.run(self.server(callback)._replay([broken, good]))
        callback.assert_awaited_once_with({"content": "good"})
        self.assertEqual(capture_spool.rejected_count(self.journal), 1)
        self.assertTrue((self.journal / "0-broken.json.replay.rejected").exists())
        self.assertEqual(self.report.call_count, 1)
        message, elapsed, kind = self.report.call_args_list[0].args
        self.assertTrue(
            message.startswith(
                "capture processing failed (kept for inspection): JSONDecodeError: "
            ),
            message,
        )
        self.assertEqual(kind, "capture_skipped")
        self.assertTrue(0.0 <= elapsed < 5.0, elapsed)

    def test_an_interrupted_replay_is_reported_word_for_word(self):
        capture_spool.claim_replay(capture_spool.write(self.journal, {"c": 1}))
        asyncio.run(self.server(mock.AsyncMock())._replay([]))
        self.assert_reported(
            "capture processing failed (kept for inspection): "
            "RuntimeError: the worker died replaying it",
            "capture_skipped",
        )

    def test_an_idle_wake_is_skipped_and_the_next_entry_stored(self):
        callback = mock.AsyncMock()
        server = self.server(callback)
        path = capture_spool.write(self.journal, {"content": "kept"})
        entries = [False, ({"content": "kept"}, path), None]
        with mock.patch.object(server, "_next", side_effect=entries):
            asyncio.run(server._consume([]))
        callback.assert_awaited_once_with({"content": "kept"})

    def test_a_listener_failure_with_a_pending_capture_says_it_is_journaled(self):
        listener = mock.Mock()
        listener.accept.side_effect = OSError("fixture listener closed")
        server = self.server(mock.AsyncMock(), listener)
        server.pending.put_nowait(None)  # the one slot is taken
        server._accept()
        message, elapsed, kind = self.report.call_args_list[-1].args
        self.assertEqual(
            (message, kind),
            (
                "pending capture left in the journal for the next worker",
                "capture_worker_lifecycle",
            ),
        )
        self.assertTrue(0.0 <= elapsed < 5.0, elapsed)

    def test_the_worker_sweeps_expired_rejections_at_start(self):
        expired = self.journal / "old.json.rejected"
        expired.write_text("{}", encoding="utf-8")
        week_and_a_day = time.time() - capture_spool.REJECTED_KEEP_SECONDS - 86400
        os.utime(expired, (week_and_a_day, week_and_a_day))
        listener = mock.Mock()
        listener.accept.side_effect = OSError("fixture listener closed")
        self.server(mock.AsyncMock(), listener).run()
        self.assertFalse(expired.exists())
