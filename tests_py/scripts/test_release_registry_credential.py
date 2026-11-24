"""Keep the MCP registry login private to publication and preserve job outcomes."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
# v1.8.1 commands/login.go:tokenFilePath and commands/publish.go:PublishCommand.
# This stand-in also writes a partial token before failing authentication.
PUBLISHER = """#!/bin/sh
set -eu
token="$HOME/.config/mcp-publisher/token.json"
case "$1" in
    login)
        test "$2" = github-oidc
        mkdir -p "$(dirname "$token")"
        echo fixture > "$token"
        echo "$HOME" > "$RUNNER_TEMP/where"
        exit "$LOGIN_STATUS" ;;
    publish)
        test "$(cat "$token")" = fixture
        touch "$RUNNER_TEMP/publish-called"
        exit "$PUBLISH_STATUS" ;;
    *) exit 2 ;;
esac
"""


@unittest.skipIf(os.name == "nt", "the MCP registry job uses an Ubuntu shell")
class RegistryCredentialLifetime(unittest.TestCase):
    def test_login_is_blocking_and_publish_is_best_effort(self):
        steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["publish-mcp-registry"][
            "steps"
        ]
        authenticated = next(
            s for s in steps if "login github-oidc" in s.get("run", "")
        )
        self.assertFalse(authenticated.get("continue-on-error", False))
        self.assertIn("./mcp-publisher publish", authenticated["run"])
        report = steps[steps.index(authenticated) + 1]
        self.assertIs(report["continue-on-error"], True)
        source = "${{ steps." + authenticated["id"] + ".outputs.status }}"
        self.assertEqual(report["env"], {"PUBLISH_STATUS": source})
        for login, publish in ((0, 0), (0, 1), (1, 0)):
            with (
                self.subTest(login=login, publish=publish),
                tempfile.TemporaryDirectory() as d,
            ):
                self.exercise(Path(d), (authenticated, report), (login, publish))

    def exercise(self, root, steps, statuses):
        login, publish = statuses
        cli = root / "mcp-publisher"
        cli.write_text(PUBLISHER)
        cli.chmod(0o700)
        output = root / "output"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root / "runner-home"),
            "RUNNER_TEMP": str(root),
            "GITHUB_OUTPUT": str(output),
            "LOGIN_STATUS": str(login),
            "PUBLISH_STATUS": str(publish),
        }
        result = subprocess.run(
            ["bash", "-e", "-c", steps[0]["run"]], cwd=root, env=env
        )
        self.assertEqual(result.returncode, login)
        private_home = Path((root / "where").read_text().strip())
        self.assertEqual(private_home.parent, root)
        self.assertNotEqual(private_home, Path(env["HOME"]))
        self.assertFalse(private_home.exists())
        self.assertFalse(list(root.rglob("token.json")))
        self.assertEqual((root / "publish-called").exists(), login == 0)
        if login:
            self.assertFalse(output.exists())
        else:
            self.assertEqual(output.read_text().strip(), f"status={publish}")
            report = subprocess.run(
                ["bash", "-e", "-c", steps[1]["run"]], cwd=root, env=env
            )
            self.assertEqual(report.returncode, publish)
