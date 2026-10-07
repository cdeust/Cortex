"""The spool drainer: one handler load per burst, one drainer at a time, nothing lost.

``test_drainer_outlives_its_parent_and_stores_the_spooled_line`` starts the real
drainer from a parent that exits at once, with the real platform's detach options
(Windows flags on the Windows CI leg), and synchronises on pipe EOF, never on a delay.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.hooks import capture_dispatch, capture_drain
from mcp_server.infrastructure import capture_spool
from tests_py.hooks.test_capture_unsupported_platform import EXPECTED
from tests_py.hooks.test_capture_worker_policy import payload

STORED = {"stored": True, "memory_id": 1}


def _stored_rows() -> int:
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return store.count_memories()["total"]


class _Spool(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.spool = capture_spool.spool_directory(Path(self.directory.name))
        self.report = mock.patch.object(capture_drain, "report_failure").start()
        self.addCleanup(mock.patch.stopall)


class TestDrain(_Spool):
    def test_stores_every_pending_file_through_the_real_handler(self):
        capture_spool.write(self.spool, EXPECTED)
        before = _stored_rows()
        capture_drain.drain(self.spool)
        self.assertEqual(_stored_rows(), before + 1)
        self.assertEqual(capture_spool.pending(self.spool), [])
        self.report.assert_not_called()

    def test_a_held_lock_exits_without_touching_the_handler(self):
        capture_spool.write(self.spool, EXPECTED)
        with (
            capture_spool.drain_lock(self.spool) as outer,
            mock.patch.object(
                capture_drain, "store", side_effect=AssertionError("handler used")
            ),
        ):
            self.assertTrue(outer)
            capture_drain.drain(self.spool)
        self.assertEqual(len(capture_spool.pending(self.spool)), 1)

    def test_refused_payload_is_rejected_and_reported_and_does_not_block_the_rest(self):
        capture_spool.write(self.spool, {**payload(), "origin_tool": "Unknown"})
        good = capture_spool.write(self.spool, EXPECTED)
        calls = []

        async def store(value):
            calls.append(value)
            if value["origin_tool"] == "Unknown":
                raise ValueError("unknown producing capture tool")
            return STORED

        with mock.patch.object(capture_drain, "store", store):
            capture_drain.drain(self.spool)
        self.assertEqual(len(calls), 2)
        self.assertFalse(good.exists())
        rejected = sorted(self.spool.glob("*" + capture_spool.REJECTED_SUFFIX))
        self.assertEqual(len(rejected), 1)
        self.assertIn("unknown producing capture tool", self.report.call_args.args[0])

    def test_handler_failure_is_rejected_and_reported_not_swallowed(self):
        capture_spool.write(self.spool, EXPECTED)

        async def store(value):
            raise RuntimeError("database is down")

        with mock.patch.object(capture_drain, "store", store):
            capture_drain.drain(self.spool)
        self.assertEqual(capture_spool.pending(self.spool), [])
        self.assertEqual(len(list(self.spool.glob("*.rejected"))), 1)
        self.assertIn("database is down", self.report.call_args.args[0])

    def test_unreadable_file_is_rejected_and_reported(self):
        (self.spool / "00000000000000000001-1-aaaaaaaa.json").write_text("{not json")
        capture_drain.drain(self.spool)
        self.assertEqual(capture_spool.pending(self.spool), [])
        self.report.assert_called_once()

    def test_file_written_during_a_pass_is_stored_by_the_rescan(self):
        capture_spool.write(self.spool, EXPECTED)
        seen = []

        async def store(value):
            seen.append(value)
            if len(seen) == 1:
                capture_spool.write(self.spool, EXPECTED)
            return STORED

        with mock.patch.object(capture_drain, "store", store):
            capture_drain.drain(self.spool)
        self.assertEqual(len(seen), 2)
        self.assertEqual(capture_spool.pending(self.spool), [])

    def test_a_hung_store_is_cancelled_rejected_and_reported_not_held_forever(self):
        hung = capture_spool.write(self.spool, EXPECTED)
        good = capture_spool.write(self.spool, {**EXPECTED, "content": "second"})
        seen = []

        async def store(value):
            seen.append(value["content"])
            if value["content"] != "second":
                await asyncio.Event().wait()  # never set: only the deadline ends it
            return STORED

        with (
            mock.patch.object(capture_drain, "store", store),
            mock.patch.object(capture_spool, "STORE_SECONDS", 0.05),
        ):
            capture_drain.drain(self.spool)
        self.assertEqual(len(seen), 2)  # the file behind the hung one was stored
        self.assertFalse(good.exists())
        self.assertFalse(hung.exists())
        self.assertEqual(len(list(self.spool.glob("*.rejected"))), 1)
        self.assertIn("TimeoutError", self.report.call_args.args[0])

    def test_reject_failure_deletes_the_file_and_reports_once_without_crashing(self):
        capture_spool.write(self.spool, EXPECTED)

        async def store(value):
            raise RuntimeError("database is down")

        with (
            mock.patch.object(capture_drain, "store", store),
            mock.patch.object(
                capture_spool, "reject", side_effect=OSError("read-only filesystem")
            ),
        ):
            capture_drain.drain(self.spool)
        self.assertEqual(capture_spool.pending(self.spool), [])
        self.report.assert_called_once()
        message = self.report.call_args.args[0]
        self.assertIn("deleted, rename failed: read-only filesystem", message)
        self.assertIn("database is down", message)

    def test_a_file_that_can_neither_be_renamed_nor_deleted_is_reported_once_per_run(
        self,
    ):
        stuck = capture_spool.write(self.spool, EXPECTED)

        async def store(value):
            raise RuntimeError("database is down")

        with (
            mock.patch.object(capture_drain, "store", store),
            mock.patch.object(
                capture_spool, "reject", side_effect=OSError("rename denied")
            ),
            mock.patch.object(Path, "unlink", side_effect=OSError("delete denied")),
        ):
            capture_drain.drain(self.spool)  # must terminate
        self.assertEqual(capture_spool.pending(self.spool), [stuck])
        self.report.assert_called_once()
        self.assertIn("left in place", self.report.call_args.args[0])

    def test_a_drain_sweeps_orphaned_partial_files(self):
        orphan = self.spool / ".dead.partial"
        orphan.write_text("{")
        long_ago = time.time() - capture_spool.PARTIAL_KEEP_SECONDS - 10
        os.utime(orphan, (long_ago, long_ago))
        capture_drain.drain(self.spool)
        self.assertFalse(orphan.exists())


# The intermediate process plays the hook: it starts the drainer through the
# production ``spawn_drainer`` (real platform options: Windows creationflags on the
# Windows leg), handing it its own stderr pipe, and exits at once.
HOOK = (
    "import sys\n"
    "from mcp_server.hooks.capture_dispatch import spawn_drainer\n"
    "spawn_drainer(sys.stderr.buffer)\n"
)


class TestDetachedDrainer(unittest.TestCase):
    def test_drainer_outlives_its_parent_and_stores_the_spooled_line(self):
        spool = capture_spool.spool_directory(capture_dispatch.CLAUDE_DIR)
        self.assertEqual(capture_spool.pending(spool), [])
        capture_spool.write(spool, EXPECTED)
        before = _stored_rows()
        hook = subprocess.Popen(
            [sys.executable, "-c", HOOK],
            stderr=subprocess.PIPE,
            cwd=Path(capture_dispatch.__file__).resolve().parents[2],
        )
        self.assertEqual(hook.wait(), 0)  # the parent is gone ...
        assert hook.stderr is not None
        # ... EOF on the pipe arrives only when the drainer, the last holder of its
        # write end, has exited: no delay decides anything.
        diagnostics = hook.stderr.read()
        hook.stderr.close()
        self.assertEqual(capture_spool.pending(spool), [], diagnostics)
        self.assertEqual(_stored_rows(), before + 1, diagnostics)


if __name__ == "__main__":
    unittest.main()
