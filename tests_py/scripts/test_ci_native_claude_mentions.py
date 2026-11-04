"""Regression guards for the owner @claude mention workflow (claude.yml)."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MENTIONS = ROOT / ".github/workflows/claude.yml"
GH_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_STUB_LOG"
[ -n "$GH_STUB_JSON" ] || exit 1
printf '%s' "$GH_STUB_JSON"
exit "${GH_STUB_EXIT:-0}"
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


def _run_guard(pull, is_pull, gh_exit=0):
    """Run the guard step's script with a stub gh and a fixture event.

    Returns the completed process and the argv lines the stub gh recorded."""
    workflow = yaml.safe_load(MENTIONS.read_text())
    script = workflow["jobs"]["claude"]["steps"][0]["run"]
    with tempfile.TemporaryDirectory() as scratch:
        gh = Path(scratch) / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        log = Path(scratch) / "gh.log"
        log.touch()
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
            "GH_STUB_LOG": str(log),
            "GH_STUB_EXIT": str(gh_exit),
        }
        result = subprocess.run(
            ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
        )
        return result, log.read_text().splitlines()


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
        # git and gh inspection commands: no bare interpreter, no gh api,
        # no gh pr comment (tag mode owns its tracking comment).
        invocation = _action_step(MENTIONS, "claude")
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            args,
            [
                "--strict-mcp-config",
                "--allowedTools",
                "Bash(uv sync:*),Bash(pytest:*),Bash(ruff check:*),"
                "Bash(ruff format --check:*),"
                "Bash(python -m mcp_server.doctor:*),"
                "Bash(python scripts/check_craftsmanship.py:*),"
                "Bash(git status:*),Bash(git diff:*),Bash(git log:*),"
                "Bash(gh pr view:*),Bash(gh pr diff:*),Bash(gh run view:*)",
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

    @unittest.skipUnless(
        shutil.which("jq") and shutil.which("bash"), "needs bash and jq"
    )
    def test_fix_target_guard_refuses_fork_and_default_branch_heads(self):
        # Behaviour, not text: the step runs under bash with a stub gh that logs
        # its argv. Every refusal names itself with a ::error:: line.
        ok, fork = _pull("cdeust/Cortex", "fix/x"), _pull("someone/Cortex", "fix/x")
        cases = {
            "same-repo feature head": (ok, True, 0, 0),
            "fork head": (fork, True, 0, 1),
            "fork head named main": (_pull("someone/Cortex", "main"), True, 0, 1),
            "same-repo main head": (_pull("cdeust/Cortex", "main"), True, 0, 1),
            "deleted fork head": ({"head": {"repo": None, "ref": "x"}}, True, 0, 1),
            "gh prints nothing and fails": (None, True, 1, 1),
            "gh prints a passing head but fails": (ok, True, 1, 1),
        }
        for name, (pull, is_pull, gh_exit, expected) in cases.items():
            with self.subTest(name):
                result, calls = _run_guard(pull, is_pull, gh_exit)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(calls, ["api repos/cdeust/Cortex/pulls/1"])
                self.assertEqual("::error::" in result.stdout, bool(expected))

    @unittest.skipUnless(
        shutil.which("jq") and shutil.which("bash"), "needs bash and jq"
    )
    def test_fix_target_guard_never_consults_gh_for_a_plain_issue(self):
        # The stub would fail if called (no JSON): a passing exit proves the
        # pull_request gate, and the empty log proves gh never ran.
        result, calls = _run_guard(None, is_pull=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

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
