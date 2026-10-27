"""Deterministic guard independent of native skill permission grants.

Source: official code-review skill allowed-tools frontmatter and Claude hooks
PreToolUse deny precedence. Commands/IDs below are synthetic attack fixtures.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GUARD = Path(__file__).resolve().parents[2] / "scripts/ci_claude_review_guard.py"
COMMAND = "gh api -X POST repos/owner/repo/pulls/1/reviews -f commit_id=abc"


def run_event(payload, context):
    return subprocess.run(
        [sys.executable, "-I", str(GUARD)],
        input=payload,
        env=context,
        text=True,
        capture_output=True,
    )


def receipts():
    return [
        dict(
            tool=name,
            decision="allow",
            sha="a" * 40,
            skill="security-review",
            verdict="verdict.md",
        )
        for name in ("Skill", "Edit", "Bash")
    ]


class ReviewGuardTests(unittest.TestCase):
    def decision(self, tool, inputs, env=None, raw=None):
        with tempfile.TemporaryDirectory() as directory:
            verdict = Path(directory) / "verdict.md"
            verdict.write_text("")
            if env and env.get("MAKE_SYMLINK"):
                victim = Path(directory) / "validator.py"
                victim.write_text("raise SystemExit(1)")
                verdict.unlink()
                verdict.symlink_to(victim)
            context = dict(
                os.environ,
                HEAD_SHA="a" * 40,
                CORTEX_REVIEW_GUARD_RECEIPT=str(Path(directory) / "receipt.jsonl"),
                CORTEX_REVIEW_FILE=str(verdict),
                CORTEX_REVIEW_SKILL="security-review",
                CORTEX_REVIEW_PUBLISH_COMMAND=COMMAND,
            )
            context.update(env or {})
            if inputs.get("file_path") == "VERDICT":
                inputs = dict(inputs, file_path=str(verdict))
            payload = raw
            if payload is None:
                payload = json.dumps(dict(tool_name=tool, tool_input=inputs))
            done = run_event(payload, context)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertNotIn("PRIVATE_TOKEN", done.stdout + done.stderr)
            decision = json.loads(done.stdout)["hookSpecificOutput"][
                "permissionDecision"
            ]
            if decision == "allow":
                self.assert_receipt(context, tool)
            return decision

    def assert_receipt(self, context, tool):
        path = Path(context["CORTEX_REVIEW_GUARD_RECEIPT"])
        row = json.loads(path.read_text())
        expected = dict(
            sha=context["HEAD_SHA"],
            skill=context["CORTEX_REVIEW_SKILL"],
            verdict=context["CORTEX_REVIEW_FILE"],
            tool=tool,
            decision="allow",
        )
        self.assertEqual(row, expected)

    def test_exact_publication_and_fixed_verdict_edit_pass(self):
        self.assertEqual(self.decision("Bash", dict(command=COMMAND)), "allow")
        self.assertEqual(self.decision("Edit", dict(file_path="VERDICT")), "allow")
        self.assertEqual(self.decision("Skill", dict(skill="security-review")), "allow")

    def test_shell_redirection_and_chaining_are_denied_even_after_skill_grants(self):
        for command in (
            "git diff HEAD HEAD --output=scripts/check.py",
            "gh pr view 1 --json body > scripts/check.py",
            COMMAND + " > scripts/check.py",
            COMMAND + "; touch injected",
            COMMAND + " && echo PRIVATE_TOKEN",
            "$(touch injected)" + COMMAND,
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decision("Bash", dict(command=command)), "deny")

    def test_other_writes_tools_and_skills_are_denied(self):
        for tool, inputs in (
            ("Edit", dict(file_path=str(GUARD))),
            ("Write", dict(file_path="VERDICT")),
            ("MultiEdit", dict(file_path="VERDICT")),
            ("Skill", dict(skill="deploy")),
            ("mcp__github_inline_comment__create_inline_comment", {}),
            ("Agent", dict(isolation="worktree")),
            ("Task", dict(mode="bypassPermissions")),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(self.decision(tool, inputs), "deny")

    def test_read_and_review_subagent_tools_pass(self):
        for tool in ("Read", "Glob", "Grep", "TodoWrite", "Agent", "Task"):
            with self.subTest(tool=tool):
                self.assertEqual(self.decision(tool, {}), "allow")

    def test_verdict_symlink_and_invalid_edit_path_are_denied(self):
        self.assertEqual(
            self.decision(
                "Edit", dict(file_path="VERDICT"), env=dict(MAKE_SYMLINK="1")
            ),
            "deny",
        )
        self.assertEqual(
            self.decision("Edit", dict(file_path="\0PRIVATE_TOKEN")), "deny"
        )

    def test_missing_context_and_malformed_hook_inputs_deny(self):
        self.assertEqual(
            self.decision(
                "Bash",
                dict(command=COMMAND),
                env=dict(CORTEX_REVIEW_PUBLISH_COMMAND=""),
            ),
            "deny",
        )
        for raw in (
            "PRIVATE_TOKEN",
            "null",
            "{}",
            '{"tool_name":"Bash","tool_input":[]}',
        ):
            self.assertEqual(self.decision("Bash", {}, raw=raw), "deny")

    def test_settings_match_all_tools_and_hook_failure_is_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            subprocess.run(
                [sys.executable, "-I", str(GUARD), "--settings", str(path)], check=True
            )
            group = json.loads(path.read_text())["hooks"]["PreToolUse"][0]
            self.assertEqual(group["matcher"], "*")
            command = group["hooks"][0]["command"]
            self.assertTrue(command.endswith(" || exit 2"))
            broken = command.replace(str(GUARD), str(Path(directory) / "missing.py"))
            done = subprocess.run(["bash", "-c", broken], capture_output=True)
            self.assertEqual(done.returncode, 2)

    def test_receipt_verification_requires_native_events_and_matching_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.jsonl"
            rows = receipts()
            command = [
                sys.executable,
                "-I",
                str(GUARD),
                "--verify",
                str(path),
                "--skill",
                "security-review",
                "--verdict",
                "verdict.md",
                "--sha",
                "a" * 40,
            ]
            for values, expected in (
                (rows, 0),
                (rows[:1], 2),
                ([], 2),
                ([dict(row, sha="b" * 40) for row in rows], 2),
            ):
                path.write_text("".join(json.dumps(row) + "\n" for row in values))
                done = subprocess.run(command, capture_output=True)
                self.assertEqual(done.returncode, expected, done.stderr)
            path.write_text("PRIVATE_TOKEN")
            done = subprocess.run(command, capture_output=True)
            self.assertEqual(done.returncode, 2)
            self.assertNotIn(b"PRIVATE_TOKEN", done.stderr)
