"""File spool primitives: atomic publication, ordering, rejection, non-blocking lock."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server.infrastructure import capture_spool
from mcp_server.shared import log_rotation


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

    def test_log_appends_across_openings(self):
        for text in ("one\n", "two\n"):
            with capture_spool.open_log(self.spool) as stream:
                stream.write(text)
        self.assertEqual(capture_spool.log_path(self.spool).read_text(), "one\ntwo\n")

    @unittest.skipIf(sys.platform == "win32", "Windows has no POSIX modes")
    def test_log_is_owner_only_even_when_it_pre_exists_with_a_wider_mode(self):
        path = capture_spool.log_path(self.spool)
        with capture_spool.open_log(self.spool):
            pass
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        path.chmod(0o644)
        with capture_spool.open_log(self.spool):
            pass
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_log_is_rotated_so_it_stays_bounded(self):
        path = capture_spool.log_path(self.spool)
        path.write_bytes(b"x" * log_rotation.MAX_LOG_BYTES)
        with capture_spool.open_log(self.spool) as stream:
            stream.write("fresh\n")
        self.assertEqual(path.read_text(), "fresh\n")
        self.assertEqual(
            path.with_name(path.name + ".1").stat().st_size, log_rotation.MAX_LOG_BYTES
        )

    def test_oldest_pending_age_is_none_when_empty_else_the_oldest_files_age(self):
        self.assertIsNone(capture_spool.oldest_pending_age(self.spool, 1000.0))
        files = [capture_spool.write(self.spool, {"n": n}) for n in range(5)]
        # mtimes set explicitly, in an order unrelated to the names, so neither the
        # clock tick nor the name order can decide the result
        mtimes = (700.0, 100.0, 900.0, 300.0, 500.0)
        for path, mtime in zip(files, mtimes, strict=True):
            os.utime(path, (mtime, mtime))
        self.assertEqual(capture_spool.oldest_pending_age(self.spool, 1000.0), 900.0)

    @unittest.skipIf(sys.platform == "win32", "Windows has no POSIX modes")
    def test_log_is_owner_only_after_a_real_rotation(self):
        path = capture_spool.log_path(self.spool)
        path.write_bytes(b"x" * log_rotation.MAX_LOG_BYTES)
        path.chmod(0o644)
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        with capture_spool.open_log(self.spool):
            pass
        previous = path.with_name(path.name + ".1")
        self.assertEqual(previous.stat().st_size, log_rotation.MAX_LOG_BYTES)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_sweep_removes_only_expired_partial_and_rejected_files(self):
        now = 10_000_000.0
        stale_partial = self.spool / ".a.partial"
        fresh_partial = self.spool / ".b.partial"
        stale_rejected = capture_spool.reject(capture_spool.write(self.spool, {"n": 1}))
        fresh_rejected = capture_spool.reject(capture_spool.write(self.spool, {"n": 2}))
        live = capture_spool.write(self.spool, {"n": 3})
        for path in (stale_partial, fresh_partial):
            path.write_text("{")
        age = {
            stale_partial: capture_spool.PARTIAL_KEEP_SECONDS + 1,
            fresh_partial: 1,
            stale_rejected: capture_spool.REJECTED_KEEP_SECONDS + 1,
            fresh_rejected: capture_spool.PARTIAL_KEEP_SECONDS + 1,
            live: capture_spool.REJECTED_KEEP_SECONDS + 1,
        }
        for path, seconds in age.items():
            os.utime(path, (now - seconds, now - seconds))
        self.assertEqual(capture_spool.sweep(self.spool, now), 2)
        self.assertEqual(
            {p for p in self.spool.iterdir()}, {fresh_partial, fresh_rejected, live}
        )

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
