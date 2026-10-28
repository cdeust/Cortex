"""Require both native review skills and their expected agent work."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_review_execution.py"
CODE, SECURITY = "code-review:code-review", "security-review"
# Source: code-review plugin 1.0.0 commands/code-review.md steps 1-4
# (eligibility, CLAUDE.md locator, summary, 2 compliance, 2 bug) + 1 security.
MIN_AGENTS = "8"


def exchange(identity, name, arguments, structured=None):
    user = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": identity, "content": "ok"}
            ]
        },
    }
    if structured is not None:
        user["tool_use_result"] = structured
    call = {"type": "tool_use", "id": identity, "name": name, "input": arguments}
    return [{"type": "assistant", "message": {"content": [call]}}, user]


def execution(skills=(CODE, SECURITY), agents=8):
    messages = []
    for index, skill in enumerate(skills):
        messages += exchange(f"s{index}", "Skill", {"skill": skill})
    for index in range(agents):
        messages += exchange(f"a{index}", "Agent", {}, {"status": "completed"})
    messages.append(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "permission_denials": [],
        }
    )
    return messages


def gate(value):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "execution.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(path),
                "--min-agents",
                MIN_AGENTS,
                "--require-skill",
                CODE,
                "--require-skill",
                SECURITY,
            ],
            text=True,
            capture_output=True,
            check=False,
        )


class SkillEvidenceTests(unittest.TestCase):
    def test_both_skills_and_eight_agents_pass(self):
        self.assertEqual(gate(execution()).returncode, 0)

    def test_missing_skill_is_rejected(self):
        for skills in ((CODE,), (SECURITY,), ()):
            with self.subTest(skills=skills):
                done = gate(execution(skills))
                self.assertEqual(done.returncode, 1)
                self.assertIn("required skill", done.stderr)

    def test_repeated_skill_is_rejected(self):
        self.assertEqual(gate(execution((CODE, SECURITY, CODE))).returncode, 1)

    def test_eligibility_skip_with_one_agent_is_rejected(self):
        done = gate(execution(agents=1))
        self.assertEqual(done.returncode, 1)
        self.assertIn("agent completion evidence", done.stderr)

    def test_slash_text_without_skill_call_is_rejected(self):
        value = execution(skills=())
        value.insert(0, {"type": "user", "message": {"content": f"/{CODE}"}})
        self.assertEqual(gate(value).returncode, 1)


if __name__ == "__main__":
    unittest.main()
