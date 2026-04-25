#!/usr/bin/env python3
"""Test script for mcp_server/hooks/agent_briefing.py.

Verifies:
  1. SubagentStart with agent_name=feynman (a genius slug) triggers briefing
     when a matching memory exists in the stubbed DB.
  2. SubagentStart with agent_name=nonexistent-agent skips gracefully (exit 0).

Stubs psycopg so no live DB is required.

Pre-condition: run from Cortex repo root (sys.path must resolve mcp_server).
Post-condition: exits 0 on pass; prints PASS/FAIL summary; exits 1 on any failure.
"""

from __future__ import annotations

import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure Cortex package is importable when run as a script.
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


# ---------------------------------------------------------------------------
# Stub psycopg so agent_briefing imports cleanly without a live PG connection.
# ---------------------------------------------------------------------------


def _make_psycopg_stub(stub_rows: list[dict]) -> types.ModuleType:
    """Build a minimal psycopg stub returning stub_rows on any execute().

    Post-condition: the returned module exposes psycopg.connect() that
    yields a connection whose execute().fetchall() returns stub_rows.
    """
    psycopg_mod = types.ModuleType("psycopg")
    rows_mod = types.ModuleType("psycopg.rows")

    cursor = MagicMock()
    cursor.fetchall.return_value = stub_rows

    conn = MagicMock()
    conn.execute.return_value = cursor

    psycopg_mod.connect = MagicMock(return_value=conn)
    rows_mod.dict_row = MagicMock()
    psycopg_mod.rows = rows_mod

    return psycopg_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_process_event(event: dict, stub_rows: list[dict]) -> tuple[str, str, int]:
    """Run process_event() in isolation, capturing stdout/stderr and exit code.

    Returns (stdout_text, stderr_text, exit_code).
    The module is reloaded so _SPECIALIST_AGENTS is re-evaluated from the
    live ~/.claude/agents dirs (dynamic load under test).
    """
    psycopg_stub = _make_psycopg_stub(stub_rows)

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    exit_code = 0

    with patch.dict(
        sys.modules, {"psycopg": psycopg_stub, "psycopg.rows": psycopg_stub.rows}
    ):
        # Force re-import so patched psycopg is visible inside _fetch_agent_context.
        if "mcp_server.hooks.agent_briefing" in sys.modules:
            del sys.modules["mcp_server.hooks.agent_briefing"]
        import mcp_server.hooks.agent_briefing as module

        try:
            with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
                module.process_event(event)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 0

    return stdout_buf.getvalue(), stderr_buf.getvalue(), exit_code


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestAgentBriefing(unittest.TestCase):
    def test_feynman_with_matching_memory_produces_briefing(self) -> None:
        """Genius agent feynman + matching memory → stdout contains Cortex Briefing.

        Pre-condition: feynman exists in ~/.claude/agents/genius/ (dynamic load).
        Post-condition: exit 0, stdout contains '## Cortex Briefing'.
        """
        stub_rows = [
            {
                "content": "feynman past lesson: always verify sources",
                "heat": 0.8,
                "agent_context": "feynman",
            },
        ]
        event = {
            "session_id": "test-session-001",
            "agent_name": "feynman",
            "agent_type": "genius",
            "prompt": "Explain the zetetic scientific standard and verify the implementation",
            "cwd": "/tmp",
        }
        stdout, stderr, code = _run_process_event(event, stub_rows)
        self.assertEqual(code, 0, f"Expected exit 0, got {code}. stderr: {stderr}")
        self.assertIn(
            "Cortex Briefing",
            stdout,
            f"Expected 'Cortex Briefing' in stdout.\nstdout: {stdout!r}\nstderr: {stderr!r}",
        )

    def test_nonexistent_agent_skips_gracefully(self) -> None:
        """Unknown agent name → exit 0 with skip log, no briefing emitted.

        Pre-condition: nonexistent-agent is not in any agent file.
        Post-condition: exit 0, stdout empty, stderr contains 'skip'.
        """
        event = {
            "session_id": "test-session-002",
            "agent_name": "nonexistent-agent",
            "agent_type": "custom",
            "prompt": "Do something with a nonexistent agent context here",
            "cwd": "/tmp",
        }
        stdout, stderr, code = _run_process_event(event, [])
        self.assertEqual(code, 0, f"Expected exit 0, got {code}. stderr: {stderr}")
        self.assertEqual(stdout.strip(), "", f"Expected empty stdout, got: {stdout!r}")
        self.assertIn(
            "skip", stderr.lower(), f"Expected 'skip' in stderr. stderr: {stderr!r}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestAgentBriefing)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nPASS: all agent-briefing tests passed.")
        sys.exit(0)
    else:
        print(
            f"\nFAIL: {len(result.failures)} failure(s), {len(result.errors)} error(s)."
        )
        sys.exit(1)
