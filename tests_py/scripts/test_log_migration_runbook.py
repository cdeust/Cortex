"""Run the documented owner migration only against synthetic temporary files."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestLogMigrationRunbook(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-log-migration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        folder = self.root / "methodology"
        folder.mkdir()
        self.legacy = folder / "session_log.json"
        self.canonical = folder / "session-log.json"
        self.canonical.write_text('{"sessions": []}', encoding="utf-8")
        runbook = (
            Path(__file__).resolve().parents[2] / "docs/runbooks/local-log-rotation.md"
        )
        self.script = runbook.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]

    def run_migration(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", "-c", self.script],
            env=dict(os.environ, CORTEX_CLAUDE_DIR=str(self.root)),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exact_duplicate_is_removed_and_canonical_retained(self) -> None:
        self.legacy.write_bytes(self.canonical.read_bytes())
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(self.canonical.read_text(), '{"sessions": []}')

    def test_different_malformed_or_duplicate_key_content_is_retained(self) -> None:
        for contents in (
            '{"sessions": ["unique"]}',
            "{",
            '{"sessions":["unique"],"sessions":[]}',
        ):
            with self.subTest(contents=contents):
                self.legacy.write_text(contents, encoding="utf-8")
                result = self.run_migration()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.legacy.read_text(), contents)
                self.assertTrue(self.canonical.exists())

    def test_json_types_and_non_finite_numbers_never_collapse_into_duplicates(
        self,
    ) -> None:
        for old, new in (
            ('{"sessions":[true]}', '{"sessions":[1]}'),
            ('{"sessions":[false]}', '{"sessions":[0]}'),
            ('{"sessions":[NaN]}', '{"sessions":[NaN]}'),
            ('{"sessions":[Infinity]}', '{"sessions":[Infinity]}'),
        ):
            with self.subTest(old=old, new=new):
                self.legacy.write_text(old, encoding="utf-8")
                self.canonical.write_text(new, encoding="utf-8")
                result = self.run_migration()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.legacy.read_text(), old)
                self.assertEqual(self.canonical.read_text(), new)

    @unittest.skipIf(
        sys.platform == "win32", "symlink privilege is not assumed on Windows"
    )
    def test_symlink_is_retained_and_target_untouched(self) -> None:
        self.legacy.symlink_to(self.canonical)
        result = self.run_migration()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.legacy.is_symlink())
        self.assertEqual(self.canonical.read_text(), '{"sessions": []}')


if __name__ == "__main__":
    unittest.main()
