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
ACTION = "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb"
GUARD = "Authorize owner fix target"
# The stub records every argument on its own line, answers with the fixture
# JSON and exits as told, so the guard's reads and refusals are observable.
GH_STUB = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg" >> "$GH_STUB_LOG"; done
[ -n "$GH_STUB_JSON" ] || exit 1
printf '%s' "$GH_STUB_JSON"
exit "${GH_STUB_EXIT:-0}"
"""
TOOLS_ON_PATH = bool(shutil.which("jq") and shutil.which("bash"))


def _job():
    return yaml.safe_load(MENTIONS.read_text())["jobs"]["claude"]


def _step(job, *, name=None, uses=None):
    return next(
        step
        for step in job["steps"]
        if (name is not None and step.get("name") == name)
        or (uses is not None and step.get("uses", "").startswith(uses))
    )


def _pull(head_repo, head_ref, default_branch="main"):
    return {
        "head": {"repo": {"full_name": head_repo}, "ref": head_ref},
        "base": {"repo": {"default_branch": default_branch}},
    }


def _run_guard(pull, is_pull, gh_exit=0, repo="cdeust/Cortex", event_missing=False):
    """Run the guard step's script with a stub gh and a fixture event.

    Returns the completed process and the argv the stub gh recorded."""
    script = _step(_job(), name=GUARD)["run"]
    with tempfile.TemporaryDirectory() as scratch:
        gh = Path(scratch) / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        log = Path(scratch) / "gh.log"
        log.touch()
        event = Path(scratch) / "event.json"
        if not event_missing:
            event.write_text(
                json.dumps({"issue": {"pull_request": {} if is_pull else None}})
            )
        env = {
            "PATH": f"{scratch}:{os.environ['PATH']}",
            "GITHUB_EVENT_PATH": str(event),
            "GH_REPO": repo,
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
        mention = _job()
        self.assertEqual(mention["permissions"]["id-token"], "write")
        invocation = _step(mention, uses=ACTION)
        self.assertNotIn("github_token", invocation["with"])
        checkout = _step(mention, uses="actions/checkout@")
        self.assertFalse(checkout["with"]["persist-credentials"])

    def test_owner_mentions_inherit_tag_mode_accept_edits(self):
        # Upstream src/modes/tag/index.ts:158-214 grants workspace edits only
        # through --permission-mode acceptEdits; base-action parse-sdk-options.ts
        # keeps the last --permission-mode, so any workflow value replaces it.
        # Runs 40645284158 and 40645479186 were refused every Edit and Write.
        mention = _job()
        invocation = _step(mention, uses=ACTION)
        self.assertEqual(invocation["uses"], ACTION)
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

    def test_owner_mentions_gate_on_the_owner_and_their_threads(self):
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
        self.assertEqual(" ".join(_job()["if"].split()), expected)

    def test_owner_mentions_allow_the_validation_commands_only(self):
        # Tag mode supplies no shell allowlist beyond its own scoped git
        # (src/modes/tag/index.ts:158-214 at the pinned SHA); headless, an
        # unlisted command is denied. The list is CLAUDE.md's validation set,
        # git inspection and gh run view: no uv sync (the job installs the
        # environment; test_uv_lock_single_source.py), no bare interpreter, no
        # gh api, no gh pr comment (tag mode owns its tracking comment).
        invocation = _step(_job(), uses=ACTION)
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            args,
            [
                "--strict-mcp-config",
                "--allowedTools",
                "Bash(pytest:*),Bash(ruff check:*),Bash(ruff format --check:*),"
                "Bash(python -m mcp_server.doctor:*),"
                "Bash(python scripts/check_craftsmanship.py:*),"
                "Bash(git status:*),Bash(git diff:*),Bash(git log:*),"
                "Bash(gh run view:*)",
                "--model",
                "claude-opus-5-5",
            ],
        )
        self.assertEqual(
            invocation["env"],
            {
                "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
                "CORTEX_RERANKER_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )

    def test_owner_mentions_install_the_tested_environment_before_the_agent(self):
        # ci.json "unit": Python 3.12, the locked dev+sqlite+codebase set; ruff
        # lives in the lint group; the embedding contract test needs the model.
        job = _job()
        steps = job["steps"]
        python = _step(job, uses="actions/setup-python@")
        locked = _step(job, uses="./.github/actions/uv-locked-install")
        project = _step(job, name="Install the project")
        model = _step(job, name="Pre-download embedding model")
        action = _step(job, uses=ACTION)
        order = [steps.index(s) for s in (python, locked, project, model, action)]
        self.assertEqual(order, sorted(order))
        self.assertEqual(python["with"], {"python-version": "3.12"})
        self.assertEqual(
            locked["with"],
            {
                "set": "--extra dev --extra sqlite --extra codebase --group lint",
                "environment": "${{ env.pythonLocation }}",
            },
        )
        self.assertEqual(project["run"], "pip install --no-deps -e .")
        self.assertIn("SentenceTransformer('all-MiniLM-L6-v2'", model["run"])

    def test_owner_mentions_authorize_the_fix_target_before_checkout(self):
        # The sender gate checks who asked, not which head the pinned action
        # checks out and pushes to (src/modes/tag/index.ts). The guard is the
        # first step, before any checkout, and carries no escape hatch.
        job = _job()
        steps = job["steps"]
        guard = _step(job, name=GUARD)
        checkout = _step(job, uses="actions/checkout@")
        self.assertIs(steps[0], guard)
        self.assertIs(steps[1], checkout)
        self.assertEqual(
            guard["env"],
            {
                "GH_TOKEN": "${{ github.token }}",
                "GH_REPO": "${{ github.repository }}",
                "ISSUE_NUMBER": "${{ github.event.issue.number }}",
            },
        )
        self.assertEqual(set(guard) - {"name", "env", "run"}, set())

    def test_owner_mentions_bound_the_run(self):
        # source: docs.github.com workflow-syntax#jobsjob_idtimeout-minutes;
        # the default is 360 minutes and the queue serializes per thread.
        self.assertEqual(_job()["timeout-minutes"], 60)

    def test_owner_mentions_serialize_branch_writes(self):
        # source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
        self.assertEqual(
            _job()["concurrency"],
            {
                "group": "claude-mentions-${{ github.event.issue.number }}",
                "cancel-in-progress": False,
                "queue": "max",
            },
        )


class FixTargetGuardBehaviour(unittest.TestCase):
    """The guard's script runs under bash with a stub gh: behaviour, not text."""

    def setUp(self):
        if not TOOLS_ON_PATH:
            if os.environ.get("CI"):
                self.fail("bash and jq must be on PATH in CI")
            self.skipTest("needs bash and jq")

    def test_refuses_fork_and_default_branch_heads(self):
        ok, fork = _pull("cdeust/Cortex", "fix/x"), _pull("someone/Cortex", "fix/x")
        cases = {
            "same-repo feature head": (ok, 0, 0, ""),
            "fork head": (fork, 0, 1, "fork or the default branch"),
            "fork head named main": (
                _pull("someone/Cortex", "main"),
                0,
                1,
                "fork or the",
            ),
            "same-repo main head": (
                _pull("cdeust/Cortex", "main"),
                0,
                1,
                "fork or the",
            ),
            "same-repo trunk head": (
                _pull("cdeust/Cortex", "trunk", "trunk"),
                0,
                1,
                "fork",
            ),
            "deleted fork head": (
                {"head": {"repo": None, "ref": "x"}},
                0,
                1,
                "fork or the",
            ),
            "gh prints nothing and fails": (None, 1, 1, "could not read PR"),
            "gh prints a passing head but fails": (ok, 1, 1, "could not read PR"),
        }
        for name, (pull, gh_exit, expected, reason) in cases.items():
            with self.subTest(name):
                result, calls = _run_guard(pull, True, gh_exit)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(calls, ["api", "repos/cdeust/Cortex/pulls/1"])
                self.assertEqual("::error::" in result.stdout, bool(expected))
                self.assertIn(reason, result.stdout)

    def test_reads_the_repository_from_the_environment(self):
        result, calls = _run_guard(
            _pull("other/repo", "fix/x"), True, repo="other/repo"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["api", "repos/other/repo/pulls/1"])

    def test_never_consults_gh_for_a_plain_issue(self):
        # The stub would fail if called (no JSON): a passing exit proves the
        # pull_request gate, and the empty log proves gh never ran.
        result, calls = _run_guard(None, is_pull=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_refuses_when_the_event_cannot_be_read(self):
        # No silent fallback: an unreadable event is a refusal, never "not a PR".
        result, calls = _run_guard(None, is_pull=False, event_missing=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("could not read the event", result.stdout)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
