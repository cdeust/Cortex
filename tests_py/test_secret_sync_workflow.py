"""Execute the real manual bootstrap step with isolated synthetic gh responses.

Source: Cortex PR831; no credentials, GitHub calls, checkout, or keychain access.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/secret-sync.yml"
START = "2026-10-29T12:00:00Z"  # Synthetic clock: no elapsed-time verdict.
NAME = "CLAUDE_CODE_OAUTH_TOKEN"
TARGET = "cdeust/ci-autonome"
OAUTH = "synthetic-oauth-value-for-workflow-test"
WRITER = "synthetic-writer-value-for-workflow-test"

# source: Cortex PR831 secret-sync.yml gh set/list invocation contract.
# This is a strict gh CLI protocol fixture, not a replacement bootstrap script.
# gh --jq evaluates this filter after fetching metadata; retain that boundary.
GH_STUB = r"""
import json, os, sys
args = sys.argv[1:]
entry = {"args": args}
expected = ["--repo", "cdeust/ci-autonome"]
if args[:2] == ["secret", "set"]:
    assert args == ["secret", "set", "CLAUDE_CODE_OAUTH_TOKEN", *expected], args
    entry["stdin"] = sys.stdin.read()
    code = 17 if os.environ["FIXTURE_FAILURE"] == "write" else 0
elif args[:2] == ["secret", "list"]:
    query = ('[.[] | select(.name == "CLAUDE_CODE_OAUTH_TOKEN" and '
             '.updatedAt >= "2026-10-29T12:00:00Z")] | length')
    assert args == ["secret", "list", *expected, "--json", "name,updatedAt",
                    "--jq", query], args
    code = 18 if os.environ["FIXTURE_FAILURE"] == "read" else 0
    rows = json.loads(os.environ["FIXTURE_METADATA"])
    count = sum(row["name"] == "CLAUDE_CODE_OAUTH_TOKEN"
                and row["updatedAt"] >= "2026-10-29T12:00:00Z" for row in rows)
    if not code:
        print(count)
else:
    raise AssertionError("unexpected gh command: " + repr(args))
with open(os.environ["FIXTURE_LOG"], "a", encoding="utf-8") as output:
    output.write(json.dumps(entry) + "\n")
if code:
    print("synthetic gh failure", file=sys.stderr)
sys.exit(code)
"""


def run_block(workflow):
    """Extract the sole actual run block without a YAML dependency."""
    blocks = re.findall(r"(?m)^([ ]+)run: \|\s*$", workflow)
    if len(blocks) != 1:
        raise AssertionError("bootstrap must have one executable run block")
    match = re.search(r"(?m)^([ ]+)run: \|\s*\n", workflow)
    indent = len(match[1])
    lines = []
    for line in workflow[match.end() :].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines)) + "\n"


class SecretSyncWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.script = run_block(cls.workflow)
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise AssertionError("bash is required to execute the workflow")

    def execute(self, *, failure="", metadata=None, github=WRITER, claude=OAUTH):
        if metadata is None:
            # source: workflow requires one metadata row at/after its start time.
            metadata = [{"name": NAME, "updatedAt": START}]
        with tempfile.TemporaryDirectory(prefix="secret-sync-test-") as scratch:
            folder = Path(scratch)
            gh = folder / "gh"
            gh.write_text(f"#!{sys.executable}\n" + GH_STUB, encoding="utf-8")
            gh.chmod(0o700)
            date = folder / "date"
            date.write_text(f"#!/bin/sh\nprintf '%s\\n' '{START}'\n", encoding="utf-8")
            date.chmod(0o700)
            log = folder / "calls.jsonl"
            # Deliberately construct a fresh environment: never inherit credentials.
            env = {
                "PATH": str(folder),
                "GH_TOKEN": github,
                "CLAUDE_TOKEN": claude,
                "FIXTURE_FAILURE": failure,
                "FIXTURE_METADATA": json.dumps(metadata),
                "FIXTURE_LOG": str(log),
            }
            result = subprocess.run(
                [
                    self.bash,
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    self.script,
                ],
                cwd=folder,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = (
                [json.loads(line) for line in log.read_text().splitlines()]
                if log.exists()
                else []
            )
        for value in (OAUTH, WRITER):
            self.assertNotIn(value, result.stdout)
            self.assertNotIn(value, result.stderr)
        return result, calls

    def assert_failed(self, **options):
        result, calls = self.execute(**options)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("::notice::synced", result.stdout + result.stderr)
        return result, calls

    def test_success_transfers_only_to_ci_autonome_using_stdin(self):
        result, calls = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [call["args"][:2] for call in calls],
            [["secret", "set"], ["secret", "list"]],
        )
        self.assertEqual(calls[0]["stdin"], OAUTH)
        for call in calls:
            self.assertEqual(call["args"][call["args"].index("--repo") + 1], TARGET)
            self.assertNotIn(OAUTH, " ".join(call["args"]))
            self.assertNotIn(WRITER, " ".join(call["args"]))
        self.assertEqual(result.stdout.strip(), f"::notice::synced {TARGET}")

    def test_write_failure_stops_before_metadata_and_success_notice(self):
        _, calls = self.assert_failed(failure="write")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"][:2], ["secret", "set"])

    def test_read_failure_has_no_success_notice(self):
        _, calls = self.assert_failed(failure="read")
        self.assertEqual(len(calls), 2)

    def test_stale_metadata_is_rejected(self):
        self.assert_failed(
            metadata=[{"name": NAME, "updatedAt": "2026-10-28T12:00:00Z"}]
        )

    def test_absent_metadata_is_rejected(self):
        self.assert_failed(metadata=[])

    def test_other_secret_metadata_cannot_confirm_copy(self):
        self.assert_failed(metadata=[{"name": "OTHER_SECRET", "updatedAt": START}])

    def test_duplicate_metadata_does_not_confirm_copy(self):
        self.assert_failed(metadata=[{"name": NAME, "updatedAt": START}] * 2)

    def test_missing_github_token_stops_before_any_gh_call(self):
        result, calls = self.assert_failed(github="")
        self.assertIn("SECRET_SYNC_TOKEN is missing", result.stdout + result.stderr)
        self.assertEqual(calls, [])

    def test_missing_claude_token_stops_before_any_gh_call(self):
        result, calls = self.assert_failed(claude="")
        self.assertIn(
            "CLAUDE_CODE_OAUTH_TOKEN is missing", result.stdout + result.stderr
        )
        self.assertEqual(calls, [])

    def test_manual_only_protected_environment_without_checkout(self):
        trigger = re.search(r"(?ms)^on:\s*\n(.*?)(?=^\S)", self.workflow)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger[1].strip(), "workflow_dispatch:")
        self.assertRegex(self.workflow, r"(?m)^permissions: \{\}\s*$")
        self.assertRegex(self.workflow, r"(?m)^    environment: secret-sync\s*$")
        self.assertIn(
            "if: github.repository == 'cdeust/Cortex' && "
            "github.ref == 'refs/heads/main'",
            self.workflow,
        )
        self.assertIn("GH_TOKEN: ${{ secrets.SECRET_SYNC_TOKEN }}", self.workflow)
        self.assertIn(
            "CLAUDE_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}", self.workflow
        )
        self.assertNotRegex(self.workflow, r"(?m)^\s*(?:-\s*)?uses:")
        self.assertNotIn("checkout", self.script)
        self.assertNotIn("git ", self.script)


if __name__ == "__main__":
    unittest.main()
