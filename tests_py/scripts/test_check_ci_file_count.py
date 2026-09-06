"""Guard against GitHub silently truncating a pull request's changed files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.check_ci_file_count import check


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_ci_file_count.py"


class FileCountTests(unittest.TestCase):
    def test_complete_api_range_is_accepted(self):
        for count in (0, 1, 3000):
            with self.subTest(count=count):
                self.assertIsNone(check(count))

    def test_truncated_api_range_is_refused(self):
        self.assertIn("3000-file API limit", check(3001))

    def test_missing_or_invalid_count_is_refused(self):
        for count in (None, True, False, -1, "1", 1.0, {}):
            with self.subTest(count=count):
                self.assertIn("nonnegative integer", check(count))

    def test_cli_refuses_truncation_with_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(json.dumps({"pull_request": {"changed_files": 3001}}))
            result = subprocess.run(
                [sys.executable, str(SCRIPT)],
                env={**os.environ, "GITHUB_EVENT_PATH": str(event)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing incomplete classification", result.stderr)
