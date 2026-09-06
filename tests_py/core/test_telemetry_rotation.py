"""Exercise the real telemetry writer in an isolated, stdlib-only process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestTelemetryRotation(unittest.TestCase):
    def test_two_samples_remain_valid_across_rotation_and_counters_accumulate(
        self,
    ) -> None:
        script = """
import json
from mcp_server.core import telemetry
from mcp_server.shared import log_rotation
telemetry.record('fixture', latency_ms=1, bytes_in=2, bytes_out=3)
log_rotation.MAX_LOG_BYTES = telemetry._LOG_PATH.stat().st_size
telemetry.record('fixture', latency_ms=4, bytes_in=5, bytes_out=6)
print(json.dumps(telemetry.snapshot()))
"""
        with tempfile.TemporaryDirectory(
            prefix="cortex-telemetry-rotation-"
        ) as directory:
            env = dict(os.environ, CORTEX_CLAUDE_DIR=directory)
            env.pop("CORTEX_TELEMETRY_DISABLED", None)
            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            root = Path(directory) / "methodology"
            old = json.loads((root / "telemetry.jsonl.1").read_text())
            new = json.loads((root / "telemetry.jsonl").read_text())
        self.assertEqual((old["bytes_in"], new["bytes_in"]), (2, 5))
        self.assertEqual((old["bytes_out"], new["bytes_out"]), (3, 6))
        self.assertEqual(json.loads(result.stdout)["fixture"]["count"], 2)
        self.assertEqual(result.stderr, "")

    def test_write_failure_still_emits_diagnostic_and_preserves_counters(self) -> None:
        script = """
from mcp_server.core import telemetry
telemetry._LOG_PATH.mkdir()
telemetry.record('fixture', latency_ms=1)
print(telemetry.snapshot()['fixture']['count'])
"""
        with tempfile.TemporaryDirectory(
            prefix="cortex-telemetry-failure-"
        ) as directory:
            env = dict(os.environ, CORTEX_CLAUDE_DIR=directory)
            env.pop("CORTEX_TELEMETRY_DISABLED", None)
            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("Cannot append telemetry sample", result.stderr)


if __name__ == "__main__":
    unittest.main()
