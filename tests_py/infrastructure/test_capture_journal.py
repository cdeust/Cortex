"""An admitted capture survives the death of the worker that acknowledged it.

Issue #716, acceptance item 2: the resident worker acknowledged a payload once
it sat in memory, so a worker that died before storing it lost a capture the
hook believed delivered. ADR-1142: the payload is journaled before the ack and
removed once stored; the next worker replays it, at most once.
"""

from __future__ import annotations

import asyncio
import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_transport import Limits
from mcp_server.shared.redaction_gate import redact_text
from tests_py.infrastructure._capture_worker_fixture import WorkerFixture


def _contents(records) -> list[str]:
    return [record["payload"]["content"] for record in records]


class TestJournalInProcess(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = Path(directory.name)
        self.report = mock.Mock()

    def server(self, callback) -> CaptureServer:
        policy = ServerPolicy(Limits(4096, 1, 300), self.report, self.journal)
        return CaptureServer(mock.Mock(), callback, policy)

    def test_an_admitted_payload_is_journaled_until_it_is_stored(self):
        seen = []

        async def callback(payload):
            seen.append(capture_spool.read(capture_spool.pending(self.journal)[0]))
            server.stopping.set()

        server = self.server(callback)
        server._admit({"content": "kept"}, deadline=float("inf"))
        asyncio.run(server._consume([]))
        self.assertEqual(seen, [{"content": "kept"}])
        self.assertEqual(list(self.journal.iterdir()), [])

    def test_a_refused_admission_leaves_nothing_to_replay(self):
        server = self.server(mock.AsyncMock())
        server.pending.put_nowait(None)  # the one slot is taken
        with self.assertRaises(TimeoutError):
            server._admit({"content": "late"}, deadline=0.0)
        with self.assertRaises(queue.Full):
            server._admit({"content": "full"}, deadline=time.monotonic() + 0.05)
        self.assertEqual(list(self.journal.iterdir()), [])

    def test_a_failed_store_is_kept_as_rejected_and_reported(self):
        callback = mock.AsyncMock(side_effect=ValueError("fixture store"))
        path = capture_spool.write(self.journal, {"content": "failed"})
        asyncio.run(self.server(callback)._replay([path]))
        self.assertEqual(capture_spool.rejected_count(self.journal), 1)
        self.assertEqual(capture_spool.pending(self.journal), [])
        self.assertEqual(self.report.call_args.args[2], "capture_skipped")

    def test_a_replay_that_killed_its_worker_is_refused_not_retried(self):
        path = capture_spool.claim_replay(
            capture_spool.write(self.journal, {"content": "poison"})
        )
        callback = mock.AsyncMock()
        asyncio.run(self.server(callback)._replay([]))
        callback.assert_not_called()
        self.assertFalse(path.exists())
        self.assertEqual(capture_spool.rejected_count(self.journal), 1)
        self.assertIn("died replaying", self.report.call_args.args[0])

    def test_a_replayed_payload_is_the_payload_the_hook_sent(self):
        # The exact-replay dedup of remember keys on content and tags, so a
        # replay matches the first store only if the journal changes nothing;
        # the hook redacts before dispatch, and redacting again is a no-op.
        content = redact_text("ran: login password=hunter2hunter2 done")
        sent = {"content": content, "tags": ["auto"], "directory": "/w"}
        path = capture_spool.write(self.journal, sent)
        self.assertEqual(capture_spool.read(path), sent)


class TestJournalAcrossWorkers(WorkerFixture):
    def test_a_capture_acknowledged_by_a_dying_worker_is_stored_by_the_next(self):
        self.send({"content": "acknowledged", "crash": True, "delay": 0.02})
        crashed = self.children.pop()
        self.assertEqual(crashed.wait(timeout=3), 1)
        self.send({"content": "next"})
        records = self.finish()
        self.assertEqual(sorted(_contents(records)), ["acknowledged", "next"])
        spool = capture_spool.spool_path(self.root)
        self.assertEqual(capture_spool.pending(spool), [])
        self.assertEqual(capture_spool.interrupted_replays(spool), [])

    def test_a_payload_that_kills_every_worker_stops_after_one_replay(self):
        # The delay holds each dying worker long enough to admit the next send.
        self.send({"content": "poison", "crash": True, "always": True, "delay": 0.5})
        self.assertEqual(self.children.pop().wait(timeout=5), 1)
        self.send({"content": "a"})  # its worker dies replaying the poison
        self.assertEqual(self.children.pop().wait(timeout=5), 1)
        self.send({"content": "b"})  # its worker refuses the poison, stores a and b
        self.assertEqual(sorted(_contents(self.finish())), ["a", "b"])
        spool = capture_spool.spool_path(self.root)
        self.assertEqual(capture_spool.rejected_count(spool), 1)
        self.assertEqual(capture_spool.pending(spool), [])
        self.assertIn("died replaying", (self.root / "errors.txt").read_text())
