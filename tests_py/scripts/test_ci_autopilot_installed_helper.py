"""Execute the copied -I helper with no model binaries or live GitHub writes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import install_ci_autopilot as installer
from tests_py.scripts.test_ci_codex_review_event_fixtures import REPO, SHA, Server


def installed(root):
    contract = root / "contract-source.md"
    contract.write_text(
        "## Contract — paste this into the delegation prompt\n"
        "Fixture contract\n---\n\n## Orchestrator side"
    )
    installer.copy_runtime(SimpleNamespace(contract=contract), root)
    return [
        sys.executable,
        "-I",
        "-B",
        str(root / "ci_autopilot_review.py"),
        "--repo",
        REPO,
        "--pr",
        "797",
        "--sha",
        SHA,
    ]


class InstalledHelper(unittest.TestCase):
    def test_real_isolated_helper_rejects_mismatched_expected_pr_before_github(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = installed(root)
            env = {**os.environ, "EXPECTED_PR": "798", "PATH": ""}
            done = subprocess.run(
                command, env=env, text=True, capture_output=True, check=True
            )
        self.assertEqual(
            json.loads(done.stdout),
            {
                "action": "none",
                "reason": "evidence_unverifiable",
                "category": "environment",
            },
        )
        self.assertIn("environment", done.stderr)

    def test_real_isolated_helper_checks_closed_pr_without_models_or_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = installed(root)
            data = Server().data["pull"]
            data["state"] = "closed"
            endpoint = "repos/" + REPO + "/pulls/797"
            log = root / "gh-calls.json"
            gh = root / "gh"
            gh.write_text(
                f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
                f"assert sys.argv[1:]==['api',{endpoint!r}]\n"
                f"Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                f"print({json.dumps(data)!r})\n"
            )
            gh.chmod(0o700)
            env = {**os.environ, "EXPECTED_PR": "797", "PATH": str(root)}
            done = subprocess.run(
                command, env=env, text=True, capture_output=True, check=True
            )
            self.assertEqual(json.loads(log.read_text()), ["api", endpoint])
        self.assertEqual(json.loads(done.stdout), {"action": "none"})
        self.assertEqual(done.stderr, "")
