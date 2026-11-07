"""Exercise grouped tool results through the real review-gate CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_review_execution.py"


def call(identity, name):
    return {"type": "tool_use", "id": identity, "name": name, "input": {}}


def result(identity, content="ok"):
    return {"type": "tool_result", "tool_use_id": identity, "content": content}


def stream(calls, results, structured=None):
    user = {"type": "user", "message": {"content": results}}
    if structured is not None:
        user["tool_use_result"] = structured
    return [
        {"type": "assistant", "message": {"content": calls}},
        user,
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "permission_denials": [],
        },
    ]


class GroupedResultTests(unittest.TestCase):
    def run_gate(self, value, *, agents=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            args = [sys.executable, str(SCRIPT), str(path)]
            return subprocess.run(
                args + (["--require-agents"] if agents else []),
                text=True,
                capture_output=True,
                check=False,
            )

    def assert_safe_rejection(self, completed, category):
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn(category, completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertNotIn(str(SCRIPT.parent), completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_non_string_first_identity_fails_by_category(self):
        for bad in ([], {}, None, 7):
            for agent_position in (0, 1):
                with self.subTest(bad=bad, agent_position=agent_position):
                    results = [result(bad), result("agent-1")]
                    if agent_position == 0:
                        results.reverse()
                    messages = stream(
                        [call("agent-1", "Agent")], results, {"status": "completed"}
                    )
                    self.assert_safe_rejection(
                        self.run_gate(messages, agents=True), "review execution:"
                    )

    def test_non_string_identity_without_agents_is_rejected(self):
        for bad in ([], {}):
            messages = stream([call("read-1", "Read")], [result(bad), result("read-1")])
            self.assert_safe_rejection(self.run_gate(messages), "no pending call")

    def test_grouped_non_agent_results_remain_valid(self):
        messages = stream(
            [call("read-1", "Read"), call("read-2", "Read")],
            [result("read-1"), result("read-2")],
        )
        completed = self.run_gate(messages)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_mixed_agent_and_non_agent_results_are_rejected(self):
        messages = stream(
            [call("agent-1", "Agent"), call("read-1", "Read")],
            [result("read-1"), result("agent-1")],
            {"status": "completed"},
        )
        self.assert_safe_rejection(
            self.run_gate(messages, agents=True), "shares a message"
        )


if __name__ == "__main__":
    unittest.main()
