"""Misses respect the existing 60/30 second windows; no DB or model used."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_server.hooks import pipeline_impact_bump as impact
from mcp_server.hooks import preemptive_context as preemptive


class MissCooldowns(unittest.TestCase):
    def setUp(self):
        tree = tempfile.TemporaryDirectory(prefix="cortex-miss-test-")
        self.addCleanup(tree.cleanup)
        self.root = Path(tree.name)
        self.event = {"tool_name": "Edit", "tool_input": {"file_path": "/no/memory.py"}}
        for module in (preemptive, impact):
            edit = patch.object(
                module, "_COOLDOWN_FILE", self.root / f"{module.__name__}.json"
            )
            edit.start()
            self.addCleanup(edit.stop)

    def exercise_window(self, module, scan):
        with patch.object(module.time, "time", return_value=1000) as clock:
            module.process_event(self.event)
            clock.return_value = 1000 + module._COOLDOWN_SECONDS - 1
            module.process_event(self.event)
            self.assertEqual(scan.call_count, 1, "a miss must not be rescanned early")
            clock.return_value = 1000 + module._COOLDOWN_SECONDS
            module.process_event(self.event)
            self.assertEqual(
                scan.call_count, 2, "the exact deadline allows another scan"
            )

    def test_preemptive_miss_waits_sixty_seconds(self):
        self.assertEqual(preemptive._COOLDOWN_SECONDS, 60)
        with patch.object(preemptive, "_prime_file_memories", return_value=0) as prime:
            self.exercise_window(preemptive, prime)

    def test_pipeline_no_symbols_waits_thirty_seconds(self):
        self.assertEqual(impact._COOLDOWN_SECONDS, 30)
        with patch.object(
            impact, "_pipeline_detect_changes", new=AsyncMock(return_value=[])
        ) as scan:
            with patch.object(impact, "_bump_heat_for_symbols") as bump:
                self.exercise_window(impact, scan)
        bump.assert_not_called()

    def test_pipeline_symbols_without_memories_wait_thirty_seconds(self):
        with patch.object(
            impact, "_pipeline_detect_changes", new=AsyncMock(return_value=["symbol"])
        ) as scan:
            with patch.object(impact, "_bump_heat_for_symbols", return_value=0) as bump:
                self.exercise_window(impact, scan)
        self.assertEqual(bump.call_count, 2)

    def test_pipeline_exception_is_logged_and_respects_window(self):
        with patch.object(
            impact,
            "_pipeline_detect_changes",
            new=AsyncMock(side_effect=RuntimeError("upstream failed")),
        ) as scan:
            with redirect_stderr(io.StringIO()) as log:
                self.exercise_window(impact, scan)
        self.assertEqual(log.getvalue().count("upstream failed"), 2)


if __name__ == "__main__":
    unittest.main()
