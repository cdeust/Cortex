"""File spool primitives: atomic publication, ordering, rejection, non-blocking lock."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.infrastructure import capture_spool


class TestCaptureSpool(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.spool = capture_spool.spool_directory(Path(self.directory.name))

    def test_spool_lives_under_the_private_capture_directory(self):
        self.assertEqual(
            self.spool,
            Path(self.directory.name).absolute() / ".capture-worker" / "spool",
        )

    @unittest.skipIf(sys.platform == "win32", "Windows has no POSIX modes")
    def test_every_created_level_is_owner_only(self):
        capture = self.spool.parent
        for directory in (capture, self.spool):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)

    def test_error_log_appends_across_openings(self):
        for text in (b"one\n", b"two\n"):
            with capture_spool.error_log(self.spool) as stream:
                stream.write(text)
        self.assertEqual((self.spool.parent / "drain.err").read_bytes(), b"one\ntwo\n")

    def test_a_written_payload_round_trips_and_leaves_no_partial_file(self):
        path = capture_spool.write(self.spool, {"content": "é☃"})
        self.assertEqual(capture_spool.read(path), {"content": "é☃"})
        self.assertEqual(sorted(p.name for p in self.spool.iterdir()), [path.name])

    def test_pending_lists_complete_files_and_ignores_partial_and_rejected_ones(self):
        first = capture_spool.write(self.spool, {"n": 1})
        second = capture_spool.write(self.spool, {"n": 2})
        (self.spool / ".x.partial").write_text("{")
        capture_spool.reject(capture_spool.write(self.spool, {"n": 3}))
        self.assertEqual(set(capture_spool.pending(self.spool)), {first, second})

    def test_reject_keeps_the_file_out_of_pending(self):
        path = capture_spool.write(self.spool, {"n": 1})
        kept = capture_spool.reject(path)
        self.assertTrue(kept.exists())
        self.assertFalse(path.exists())
        self.assertEqual(capture_spool.pending(self.spool), [])

    def test_non_object_json_is_refused(self):
        path = self.spool / "1.json"
        path.write_text("[1]")
        with self.assertRaisesRegex(ValueError, "not a JSON object"):
            capture_spool.read(path)

    def test_second_holder_loses_without_waiting_and_lock_is_reusable(self):
        with capture_spool.drain_lock(self.spool) as first:
            with capture_spool.drain_lock(self.spool) as second:
                self.assertEqual((first, second), (True, False))
        with capture_spool.drain_lock(self.spool) as again:
            self.assertTrue(again)

    def test_an_unexpected_lock_error_propagates(self):
        failure = OSError(5, "I/O error")
        with mock.patch.object(capture_spool, "_try_lock", side_effect=failure):
            with self.assertRaises(OSError):
                with capture_spool.drain_lock(self.spool):
                    pass


if __name__ == "__main__":
    unittest.main()
