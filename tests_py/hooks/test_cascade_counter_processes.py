"""One-shot, concurrent hook regression tests: stdlib only, no DB/model."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mcp_server.hooks import post_tool_capture as hook
from mcp_server.infrastructure import hook_cascade_counter as counter
from mcp_server.infrastructure.groomer_coordinator_io import DecisionLock

_CHILD = """
import os
from pathlib import Path
from mcp_server.hooks import post_tool_capture as hook
root = Path(os.environ['CORTEX_CLAUDE_DIR'])
def advance():
    with (root / 'advances.txt').open('a', encoding='utf-8') as output:
        output.write('advanced\\n')
hook._run_cascade = advance
hook._store_memory = lambda *args: None
hook.main()
"""


class CascadeCounterProcesses(unittest.TestCase):
    def setUp(self):
        self.tree = tempfile.TemporaryDirectory(prefix="cortex-cascade-test-")
        self.addCleanup(self.tree.cleanup)
        self.root = Path(self.tree.name)
        self.patch = patch.object(counter, "METHODOLOGY_DIR", self.root / "methodology")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def event(self, index=0, transcript="session.jsonl"):
        return {
            "tool_name": "Task" if index % 2 else "Bash",
            "transcript_path": str(self.root / transcript),
            "session_id": f"changing-envelope-{index}",
            "tool_response": "Build succeeded; enough output to capture this event.",
        }

    def child(self, event):
        env = {**os.environ, "CORTEX_CLAUDE_DIR": str(self.root), "DATABASE_URL": ""}
        result = subprocess.run(
            [sys.executable, "-S", "-c", _CHILD],
            cwd=Path(__file__).resolve().parents[2],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,  # source: plugin.json PostToolUse capture timeout.
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("cascade failed", result.stderr)
        return result

    def state(self, transcript="session.jsonl"):
        directory = counter._session_directory(str(self.root / transcript))
        return json.loads((directory / "counter.json").read_text())

    def advances(self):
        output = self.root / "advances.txt"
        return output.read_text().splitlines() if output.exists() else []

    def test_twentieth_and_fortieth_separate_processes_advance(self):
        for index in range(40):
            self.child(self.event(index))
            self.assertEqual(len(self.advances()), (index + 1) // 20)
        self.assertEqual(self.state(), {"tool_calls": 40, "completed": 40})

    def test_concurrent_processes_preserve_every_tick_and_due_interval(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.child, [self.event(index) for index in range(40)]))
        self.assertEqual(self.state()["tool_calls"], 40)
        # Last contenders may leave one pending interval; a later event drains it.
        self.child(self.event(40))
        self.assertEqual(self.state(), {"tool_calls": 41, "completed": 40})
        self.assertEqual(len(self.advances()), 2)

    def test_distinct_transcripts_do_not_share_counter(self):
        for _ in range(19):
            counter.advance_after_tool("one.jsonl", lambda: self.fail("too early"))
            counter.advance_after_tool("two.jsonl", lambda: self.fail("too early"))
        advanced = []
        counter.advance_after_tool("one.jsonl", lambda: advanced.append("one"))
        self.assertEqual(advanced, ["one"])
        directory = counter._session_directory("two.jsonl")
        self.assertEqual(counter._read_counter(directory)["tool_calls"], 19)

    def test_resume_same_transcript_keeps_count_despite_event_session_id(self):
        advanced = []
        with patch.object(hook, "_run_cascade", lambda: advanced.append(True)):
            with redirect_stderr(io.StringIO()):
                for index in range(20):
                    hook.process_event({**self.event(index), "tool_name": "Task"})
        self.assertEqual(advanced, [True])
        self.assertEqual(self.state(), {"tool_calls": 20, "completed": 20})

    def test_busy_cascade_retains_deadlines_and_does_not_lock_counter(self):
        transcript = "session.jsonl"
        directory = counter._session_directory(transcript)
        advanced = []
        with DecisionLock(directory.parent / "cascade.lock") as acquired:
            self.assertTrue(acquired)
            for _ in range(40):
                status = counter.advance_after_tool(
                    transcript, lambda: advanced.append(1)
                )
            self.assertEqual(status, "pending")
            self.assertEqual(
                counter._read_counter(directory), {"tool_calls": 40, "completed": 0}
            )
        for _ in range(2):
            counter.advance_after_tool(transcript, lambda: advanced.append(1))
        self.assertEqual(advanced, [1, 1])
        self.assertEqual(
            counter._read_counter(directory), {"tool_calls": 42, "completed": 40}
        )

    def test_two_sessions_share_execution_lock_and_keep_separate_due_work(self):
        for _ in range(19):
            counter.advance_after_tool("one.jsonl", lambda: None)
            counter.advance_after_tool("two.jsonl", lambda: None)
        advanced = []

        def first_cascade():
            advanced.append("one")
            status = counter.advance_after_tool(
                "two.jsonl", lambda: advanced.append("two")
            )
            self.assertEqual(status, "pending")

        counter.advance_after_tool("one.jsonl", first_cascade)
        self.assertEqual(advanced, ["one"])
        counter.advance_after_tool("two.jsonl", lambda: advanced.append("two"))
        self.assertEqual(advanced, ["one", "two"])

    def test_failure_does_not_acknowledge_due_cascade(self):
        transcript = "session.jsonl"
        for _ in range(19):
            counter.advance_after_tool(transcript, lambda: None)
        with self.assertRaisesRegex(RuntimeError, "DB failed"):
            counter.advance_after_tool(transcript, self.fail_cascade)
        directory = counter._session_directory(transcript)
        self.assertEqual(
            counter._read_counter(directory), {"tool_calls": 20, "completed": 0}
        )
        self.assertEqual(
            counter.advance_after_tool(transcript, lambda: None), "advanced"
        )
        self.assertEqual(
            counter._read_counter(directory), {"tool_calls": 21, "completed": 20}
        )

    @staticmethod
    def fail_cascade():
        raise RuntimeError("DB failed")

    def test_cascade_never_holds_counter_lock_during_database_callback(self):
        for _ in range(19):
            counter.advance_after_tool("session.jsonl", lambda: None)
        counter.advance_after_tool("session.jsonl", lambda: self.child(self.event(20)))
        self.assertEqual(self.state(), {"tool_calls": 21, "completed": 20})

    def test_missing_identity_logs_and_capture_still_runs(self):
        event = self.event()
        del event["transcript_path"]
        with patch.object(hook, "_store_memory") as captured:
            with redirect_stderr(io.StringIO()) as log:
                hook.process_event(event)
        captured.assert_called_once()
        self.assertIn("missing transcript identity", log.getvalue())
        self.assertFalse((self.root / "methodology").exists())

    def test_invalid_identity_is_not_fabricated(self):
        for invalid in (None, "", " ", [], 12, "/", "\x00.jsonl"):
            with self.subTest(identity=invalid):
                with self.assertRaises(ValueError):
                    counter.advance_after_tool(invalid, lambda: self.fail("invalid"))

    def test_corrupt_counter_is_preserved_and_logged(self):
        directory = counter._session_directory(self.event()["transcript_path"])
        directory.mkdir(parents=True)
        state_path = directory / "counter.json"
        state_path.write_text("corrupt")
        with patch.object(hook, "_store_memory") as captured:
            with redirect_stderr(io.StringIO()) as log:
                hook.process_event(self.event())
        captured.assert_called_once()
        self.assertIn("cascade failed", log.getvalue())
        self.assertEqual(state_path.read_text(), "corrupt")

    def test_structured_cascade_error_leaves_interval_pending(self):
        for _ in range(19):
            counter.advance_after_tool("session.jsonl", lambda: None)
        modules = {
            "mcp_server.handlers.consolidation.cascade": SimpleNamespace(
                run_cascade_advancement=MagicMock(return_value={"error": "DB failed"})
            ),
            "mcp_server.infrastructure.memory_store": SimpleNamespace(
                get_shared_store=MagicMock(return_value=object())
            ),
        }
        with patch.dict(sys.modules, modules):
            with patch.object(hook, "_store_memory") as captured:
                with redirect_stderr(io.StringIO()) as log:
                    hook.process_event(self.event())
        captured.assert_called_once()
        self.assertIn("DB failed", log.getvalue())
        self.assertEqual(self.state(), {"tool_calls": 20, "completed": 0})

    def test_unavailable_execution_lock_is_reported_and_preserves_due_work(self):
        for _ in range(19):
            counter.advance_after_tool("session.jsonl", lambda: None)
        lock = MagicMock()
        lock.return_value.__enter__.return_value = False
        with patch.object(counter, "DecisionLock", lock):
            with patch.object(hook, "_store_memory") as captured:
                with redirect_stderr(io.StringIO()) as log:
                    hook.process_event(self.event())
        captured.assert_called_once()
        self.assertIn("execution lock busy or unavailable", log.getvalue())
        self.assertEqual(self.state(), {"tool_calls": 20, "completed": 0})

    def test_invalid_counter_values_are_rejected(self):
        directory = counter._session_directory("session.jsonl")
        directory.mkdir(parents=True)
        for state in (
            [],
            {},
            {"tool_calls": True, "completed": 0},
            {"tool_calls": -1, "completed": 0},
            {"tool_calls": 20, "completed": 21},
            {"tool_calls": 40, "completed": 19},
        ):
            with self.subTest(state=state):
                (directory / "counter.json").write_text(json.dumps(state))
                with self.assertRaises(ValueError):
                    counter.advance_after_tool("session.jsonl", lambda: None)

    def test_write_failure_prevents_advancement_and_remains_visible(self):
        with patch.object(counter, "atomic_write_json", return_value=False):
            with self.assertRaisesRegex(OSError, "write failed"):
                counter.advance_after_tool(
                    "session.jsonl", lambda: self.fail("I/O failed")
                )


if __name__ == "__main__":
    unittest.main()
