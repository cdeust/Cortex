"""Behaviour of the fix-target guard of the owner @claude mention workflow."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MENTIONS = ROOT / ".github/workflows/claude.yml"
GUARD = "Authorize owner fix target"
MISSING = object()  # Sentinel: write no event file at all.
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


def _run_guard(pull, is_pull, gh_exit=0, repo="cdeust/Cortex", event_body=None):
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
        if event_body is None:
            event.write_text(
                json.dumps({"issue": {"pull_request": {} if is_pull else None}})
            )
        elif event_body != MISSING:
            event.write_text(event_body)
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
        # No silent fallback: a missing, empty or non-boolean event is a
        # refusal, never "not a PR". The empty file makes jq exit 0 with no
        # output, so only the value check catches it.
        cases = {
            "missing file": MISSING,
            "empty file": "",
            "null": "null",
            "no issue": "{}",
        }
        for name, body in cases.items():
            with self.subTest(name):
                result, calls = _run_guard(None, is_pull=False, event_body=body)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("could not read the event", result.stdout)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
