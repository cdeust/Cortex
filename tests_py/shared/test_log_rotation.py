"""Small stdlib rotation tests; all files and processes use synthetic data."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server.shared import log_rotation


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
        process.wait()


class TestLogRotation(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-rotation-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "log.jsonl"
        self.previous = self.path.with_name(self.path.name + ".1")

    def append(self, text: str) -> None:
        with log_rotation.open_rotating_log(
            self.path, len(text.encode("utf-8"))
        ) as stream:
            stream.write(text)

    def test_below_threshold_appends_without_rotation(self) -> None:
        self.append("first\n")
        self.append("second\n")
        self.assertEqual(self.path.read_text(), "first\nsecond\n")
        self.assertFalse(self.previous.exists())

    def test_actual_f9_threshold_rotates_before_worker_open(self) -> None:
        self.assertEqual(log_rotation.MAX_LOG_BYTES, 196_000 * 30)
        with self.path.open("wb") as stream:
            stream.truncate(
                log_rotation.MAX_LOG_BYTES
            )  # Sparse fixture, no log corpus.
        with log_rotation.open_rotating_log(self.path) as stream:
            self.assertEqual(self.previous.stat().st_size, log_rotation.MAX_LOG_BYTES)
            self.assertEqual(self.path.stat().st_size, 0)
            stream.write("worker\n")
        self.assertEqual(self.path.read_text(), "worker\n")
        self.assertTrue(stream.closed)

    def test_utf8_bytes_trigger_rotation_and_keep_complete_records(self) -> None:
        first, second = "é\n", "à\n"
        with patch.object(
            log_rotation, "MAX_LOG_BYTES", len((first + "x").encode("utf-8"))
        ):
            self.append(first)
            self.append(second)
        self.assertEqual(self.previous.read_text(), first)
        self.assertEqual(self.path.read_text(), second)

    def test_only_one_previous_segment_is_retained(self) -> None:
        with patch.object(log_rotation, "MAX_LOG_BYTES", len("first\n")):
            for line in ("first\n", "next!\n", "last!\n"):
                self.append(line)
        self.assertEqual(self.path.read_text(), "last!\n")
        self.assertEqual(self.previous.read_text(), "next!\n")
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {"log.jsonl", "log.jsonl.1", "log.jsonl.lock"},
        )

    def test_single_oversized_record_is_preserved_whole(self) -> None:
        with patch.object(log_rotation, "MAX_LOG_BYTES", len("old\n")):
            self.append("old\n")
            self.append("one oversized complete record\n")
        self.assertEqual(self.previous.read_text(), "old\n")
        self.assertEqual(self.path.read_text(), "one oversized complete record\n")

    def test_error_closes_stream_and_releases_lock_for_next_write(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with log_rotation.open_rotating_log(self.path) as stream:
                raise RuntimeError("fixture failure")
        self.assertTrue(stream.closed)
        self.append("next write\n")
        self.assertEqual(self.path.read_text(), "next write\n")

    def test_rotation_error_preserves_existing_file_and_propagates(self) -> None:
        self.path.write_text("first\n", encoding="utf-8")
        with patch.object(log_rotation, "MAX_LOG_BYTES", len("first\n")):
            with patch.object(
                Path, "replace", side_effect=PermissionError("busy file")
            ):
                with self.assertRaisesRegex(PermissionError, "busy file"):
                    self.append("next\n")
        self.assertEqual(self.path.read_text(), "first\n")
        self.assertFalse(self.previous.exists())

    @unittest.skipIf(
        sys.platform == "win32", "symlink privilege is not assumed on Windows"
    )
    def test_log_and_archive_symlinks_are_refused(self) -> None:
        target = self.root / "target.txt"
        target.write_text("untouched", encoding="utf-8")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(OSError, "regular file"):
            self.append("new\n")
        self.path.unlink()
        self.path.write_text("old\n", encoding="utf-8")
        self.previous.symlink_to(target)
        with patch.object(log_rotation, "MAX_LOG_BYTES", len("old\n")):
            with self.assertRaisesRegex(OSError, "regular file"):
                self.append("new\n")
        self.assertEqual(target.read_text(), "untouched")

    def test_two_independent_processes_keep_both_records_across_rotation(self) -> None:
        script = """
import json, sys
from pathlib import Path
from mcp_server.shared import log_rotation
line = json.dumps({'writer': sys.argv[2]}) + '\\n'
log_rotation.MAX_LOG_BYTES = len(line.encode('utf-8'))
with log_rotation.open_rotating_log(
    Path(sys.argv[1]), len(line.encode('utf-8'))
) as out:
    out.write(line)
"""
        processes = [
            subprocess.Popen([sys.executable, "-c", script, str(self.path), label])
            for label in ("one", "two")
        ]
        for process in processes:
            self.addCleanup(_stop_process, process)
        for process in processes:
            self.assertEqual(process.wait(timeout=10), 0)
        records = [json.loads(path.read_text()) for path in (self.path, self.previous)]
        self.assertEqual({record["writer"] for record in records}, {"one", "two"})


if __name__ == "__main__":
    unittest.main()
