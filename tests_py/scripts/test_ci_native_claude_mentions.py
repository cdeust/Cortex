"""Regression guards for the owner @claude mention workflow (claude.yml)."""

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MENTIONS = ROOT / ".github/workflows/claude.yml"
GH_STUB = """#!/bin/sh
[ -n "$GH_STUB_JSON" ] || exit 1
printf '%s' "$GH_STUB_JSON"
"""


def _action_step(path, job):
    workflow = yaml.safe_load(path.read_text())
    return next(
        step
        for step in workflow["jobs"][job]["steps"]
        if "claude-code-action@" in step.get("uses", "")
    )


def _pull(head_repo, head_ref):
    return {
        "head": {"repo": {"full_name": head_repo}, "ref": head_ref},
        "base": {"repo": {"default_branch": "main"}},
    }


def _run_guard(pull, is_pull):
    """Run the guard step's script with a stub gh and a fixture event."""
    workflow = yaml.safe_load(MENTIONS.read_text())
    script = workflow["jobs"]["claude"]["steps"][0]["run"]
    with tempfile.TemporaryDirectory() as scratch:
        gh = Path(scratch) / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        event = Path(scratch) / "event.json"
        event.write_text(
            json.dumps({"issue": {"pull_request": {} if is_pull else None}})
        )
        env = {
            "PATH": f"{scratch}:{os.environ['PATH']}",
            "GITHUB_EVENT_PATH": str(event),
            "GH_REPO": "cdeust/Cortex",
            "ISSUE_NUMBER": "1",
            "GH_STUB_JSON": json.dumps(pull) if pull is not None else "",
        }
        return subprocess.run(
            ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
        )


class OwnerMentionTests(unittest.TestCase):
    def test_owner_mentions_keep_app_authentication(self):
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        self.assertEqual(mention["permissions"]["id-token"], "write")
        invocation = next(
            step
            for step in mention["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertNotIn("github_token", invocation["with"])
        checkout = next(
            step
            for step in mention["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertFalse(checkout["with"]["persist-credentials"])

    def test_owner_mentions_inherit_tag_mode_accept_edits(self):
        # Upstream src/modes/tag/index.ts:158-214 grants workspace edits only
        # through --permission-mode acceptEdits; base-action parse-sdk-options.ts
        # keeps the last --permission-mode, so any workflow value replaces it.
        # Runs 40645284158 and 40645479186 were refused every Edit and Write.
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        invocation = next(
            step
            for step in mention["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertEqual(
            invocation["uses"],
            "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb",
        )
        self.assertEqual(
            set(invocation["with"]),
            {"claude_code_oauth_token", "include_comments_by_actor", "claude_args"},
        )
        self.assertEqual(
            invocation["with"]["include_comments_by_actor"],
            "${{ github.repository_owner }}",
        )
        self.assertNotIn("--permission-mode", invocation["with"]["claude_args"])
        self.assertEqual(mention["permissions"]["contents"], "write")
        # Pin both branches and the outer sender gate, including their grouping.
        expected = (
            "github.event.sender.login == github.repository_owner "
            "&& ((github.event_name == 'issue_comment' "
            "&& contains(github.event.comment.body, '@claude') "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& github.event.comment.user.login != 'claude[bot]' "
            "&& github.event.comment.user.type != 'Bot') "
            "|| (github.event_name == 'issues' "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& (contains(github.event.issue.body, '@claude') "
            "|| contains(github.event.issue.title, '@claude'))))"
        )
        self.assertEqual(" ".join(mention["if"].split()), expected)

    def test_owner_mentions_allow_the_validation_commands_only(self):
        # Tag mode supplies no shell allowlist beyond its own scoped git
        # (src/modes/tag/index.ts:158-214 at the pinned SHA); headless, an
        # unlisted command is denied. The list is CLAUDE.md's validation set,
        # read-only git and read-only gh: no bare interpreter, no gh api.
        invocation = _action_step(MENTIONS, "claude")
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            args,
            [
                "--strict-mcp-config",
                "--allowedTools",
                "Bash(uv sync:*),Bash(pytest:*),Bash(ruff check:*),Bash(ruff format:*),"
                "Bash(python -m mcp_server.doctor:*),"
                "Bash(python scripts/check_craftsmanship.py:*),"
                "Bash(git status:*),Bash(git diff:*),Bash(git log:*),"
                "Bash(gh pr view:*),Bash(gh pr diff:*),Bash(gh pr comment:*),"
                "Bash(gh run view:*)",
                "--model",
                "claude-opus-5-5",
            ],
        )
        self.assertEqual(
            {k: v for k, v in invocation["env"].items() if k.endswith("OFFLINE")},
            {
                "CORTEX_RERANKER_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )

    def test_owner_mentions_authorize_the_fix_target_before_checkout(self):
        # The sender gate checks who asked, not which head the pinned action
        # checks out and pushes to (src/modes/tag/index.ts). The guard is the
        # first step, before any checkout, and carries no escape hatch.
        workflow = yaml.safe_load(MENTIONS.read_text())
        steps = workflow["jobs"]["claude"]["steps"]
        guard = steps[0]
        self.assertEqual(guard["name"], "Authorize owner fix target")
        self.assertTrue(steps[1].get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(
            guard["env"],
            {
                "GH_TOKEN": "${{ github.token }}",
                "GH_REPO": "${{ github.repository }}",
                "ISSUE_NUMBER": "${{ github.event.issue.number }}",
            },
        )
        self.assertEqual(set(guard) - {"name", "env", "run"}, set())

    def test_fix_target_guard_refuses_fork_and_default_branch_heads(self):
        # Behaviour, not text: the step runs under bash with a stub gh.
        cases = {
            "same-repo feature head": (_pull("cdeust/Cortex", "fix/x"), 0, True),
            "fork head": (_pull("someone/Cortex", "fix/x"), 1, True),
            "fork head named main": (_pull("someone/Cortex", "main"), 1, True),
            "same-repo main head": (_pull("cdeust/Cortex", "main"), 1, True),
            "deleted fork head": ({"head": {"repo": None, "ref": "x"}}, 1, True),
            "gh failure": (None, 1, True),
            "plain issue": (_pull("cdeust/Cortex", "fix/x"), 0, False),
        }
        for name, (pull, expected, is_pull) in cases.items():
            with self.subTest(name):
                result = _run_guard(pull, is_pull)
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("::error::", result.stdout + result.stderr)

    def test_owner_mentions_bound_the_run(self):
        # source: docs.github.com workflow-syntax#jobsjob_idtimeout-minutes;
        # the default is 360 minutes and the queue serializes per thread.
        workflow = yaml.safe_load(MENTIONS.read_text())
        self.assertEqual(workflow["jobs"]["claude"]["timeout-minutes"], 60)

    def test_owner_mentions_serialize_branch_writes(self):
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        # source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
        self.assertEqual(
            mention["concurrency"],
            {
                "group": "claude-mentions-${{ github.event.issue.number }}",
                "cancel-in-progress": False,
                "queue": "max",
            },
        )
