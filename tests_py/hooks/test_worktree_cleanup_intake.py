"""External process proof that SessionEnd is independent of disposal locks.

source: ADR-1092 — Codex's SessionEnd dispatch has a three-second budget.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "plugins/hypermnesia-mcp-codex/scripts"),
)
import cleanup_intake as intake
from cleanup_registry import registry
import disk_hygiene


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="cleanup-intake-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.args = SimpleNamespace(
            state=str(self.root / "ledger.json"),
            host="codex",
            session=str(uuid.uuid4()),
            command="hook",
            event="SessionEnd",
        )
        self.env = dict(
            os.environ,
            CODEX_HOME=str(self.root / "codex"),
            CORTEX_CLAUDE_DIR=str(self.root / "claude"),
            CLAUDE_CODE_TMPDIR=str(self.root / "tmp"),
            CORTEX_CLEANUP_TRANSCRIPTS="keep",
            PYTHONDONTWRITEBYTECODE="1",
        )

    def test_end_subprocess_completes_while_global_ledger_is_locked(self):
        command = [
            sys.executable,
            disk_hygiene.__file__,
            "--state",
            self.args.state,
            "--host",
            "codex",
            "--session",
            self.args.session,
            "hook",
            "SessionEnd",
        ]
        with registry(self.args.state):
            started = time.monotonic()
            completed = subprocess.run(
                command,
                input=json.dumps({"cwd": str(self.root)}),
                text=True,
                capture_output=True,
                env=self.env,
                timeout=3,  # source: ADR-1092 (native Codex SessionEnd maximum).
            )
            elapsed = time.monotonic() - started
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertEqual(
                json.loads(completed.stdout)["ended"], "codex:" + self.args.session
            )
            for consumer in ("worktree", "host"):
                events = intake.read_pending(self.args.state, consumer)
                self.assertEqual(events[0][1]["session"], self.args.session)
        # Receipt exists before lock release; elapsed time is an observation.
        print(f"Codex locked-ledger SessionEnd: {elapsed:.3f}s (host budget 3s)")

    def test_worktree_ack_does_not_consume_host_event(self):
        intake.record_end(self.args, {})
        events = intake.read_pending(self.args.state, "worktree")
        intake.acknowledge(events)
        self.assertEqual(intake.read_pending(self.args.state, "worktree"), [])
        self.assertEqual(len(intake.read_pending(self.args.state, "host")), 1)

    def test_later_end_survives_earlier_ack(self):
        intake.record_end(self.args, {})
        snapshot = intake.read_pending(self.args.state, "worktree")
        intake.record_end(self.args, {})
        intake.acknowledge(snapshot)
        self.assertEqual(len(intake.read_pending(self.args.state, "worktree")), 1)

    def test_resume_consumes_old_marker_without_ending_current_owner(self):
        intake.record_end(self.args, {})
        self.args.event = "SessionStart"
        with patch.object(
            disk_hygiene.host_cleanup, "after_hook", side_effect=lambda a, p, r: r
        ):
            disk_hygiene.run_command(self.args, {"cwd": str(self.root)})
        with registry(self.args.state) as state:
            self.assertNotIn("codex:" + self.args.session, state["_ended"])
        self.assertEqual(intake.read_pending(self.args.state, "worktree"), [])

    def test_invalid_ledger_does_not_lose_end_event(self):
        Path(self.args.state).write_text("not-json")
        disk_hygiene.run_command(self.args, {})
        self.assertEqual(len(intake.read_pending(self.args.state, "worktree")), 1)
        self.assertEqual(Path(self.args.state).read_text(), "not-json")
