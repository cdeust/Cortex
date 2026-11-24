"""Exercise the release step with Git, a disposable identity and no network."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
ENGINES = ("pipeline.yml", "pipeline-post-merge.yml")
KEY = "${{ secrets.RELEASE_TAG_SSH_KEY }}"
# Git invokes this fixture in place of an SSH connection. The real agent must
# sign with the matching private key before the local bare remote accepts Git.
SSH_TRANSPORT = """#!/bin/sh
set -eu
printf '%s\\n' "$SSH_AUTH_SOCK" > "$RUNNER_TEMP/socket"
test -z "${SSH_KEY+x}"
ssh-add -T "$RUNNER_TEMP/identity.pub"
case "$*" in
  *git-upload-pack*) exec git-upload-pack "$RUNNER_TEMP/remote" ;;
  *git-receive-pack*)
    echo "authenticated push" > "$RUNNER_TEMP/verified"
    test "$PUBLISH_STATUS" = 0 || exit "$PUBLISH_STATUS"
    exec git-receive-pack "$RUNNER_TEMP/remote" ;;
  *) exit 1 ;;
esac
"""


def git(repo, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", repo, *args],
        input=input_text,
        text=True,
        check=True,
        capture_output=True,
    ).stdout.strip()


def prepare(root):
    repo = root / "release-repo"
    git(root, "init", "--bare", str(repo))
    git(root, "init", "--bare", str(root / "remote"))
    git(repo, "remote", "add", "origin", "git@github.com:fixture/repo.git")
    tree = git(repo, "mktree", input_text="")
    sha = git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.org",
        "commit-tree",
        tree,
        "-m",
        "release fixture",
    )
    identity = root / "identity"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", identity], check=True
    )
    key = identity.read_text()
    identity.unlink()
    transport = root / "ssh"
    transport.write_text(SSH_TRANSPORT)
    transport.chmod(0o700)
    env = {
        **os.environ,
        "RUNNER_TEMP": str(root),
        "SSH_KEY": key,
        "TESTED_SHA": sha,
        "RELEASE_TAGS": '["v1.0.0"]',
        "GITHUB_STEP_SUMMARY": str(root / "summary"),
        "GIT_SSH_VARIANT": "ssh",
        "PATH": str(root) + os.pathsep + os.environ["PATH"],
    }
    env.pop("SSH_AUTH_SOCK", None)
    env.pop("SSH_AGENT_PID", None)
    return repo, env


class ReleaseCredentialLifetime(unittest.TestCase):
    def test_release_key_is_scoped_to_publication(self):
        for name in ENGINES:
            tag = yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]["tag"]
            with self.subTest(engine=name):
                recipients = [
                    step.get("id") for step in tag["steps"] if KEY in str(step)
                ]
                self.assertEqual(recipients, ["publish"])
                self.assertEqual(tag["permissions"], {"contents": "read"})

    def test_repository_checkouts_discard_credentials(self):
        for path in WORKFLOWS.glob("*.yml"):
            jobs = yaml.safe_load(path.read_text())["jobs"]
            for job, body in jobs.items():
                for step in body.get("steps", []):
                    if step.get("uses", "").startswith("actions/checkout@"):
                        with self.subTest(workflow=path.name, job=job):
                            self.assertIs(
                                step.get("with", {}).get("persist-credentials"), False
                            )

    def test_catalog_pushes_authenticate_only_for_their_git_command(self):
        workflow = yaml.safe_load((WORKFLOWS / "publish-ccplugins.yml").read_text())
        steps = workflow["jobs"]["sync"]["steps"]
        pushes = [s for s in steps if "${{ secrets.CCPLUGINS_PAT }}" in str(s)]
        self.assertEqual(
            [s["name"] for s in pushes],
            ["Sync fork with upstream", "Push + open (or update) PR"],
        )
        for step in pushes:
            self.assertEqual(step["env"]["GH_TOKEN"], "${{ secrets.CCPLUGINS_PAT }}")
            self.assertIn(
                "git -c credential.helper= "
                "-c 'credential.helper=!gh auth git-credential' push",
                step["run"],
            )

    @unittest.skipIf(os.name == "nt", "the tag job runs on Ubuntu with POSIX OpenSSH")
    def test_identity_lifetime(self):
        for name in ENGINES:
            tag = yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]["tag"]
            publish = next(step for step in tag["steps"] if step.get("id") == "publish")
            for status in (0, 1):
                with (
                    self.subTest(engine=name, status=status),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    self.exercise(Path(tmp), publish["run"], status)

    def exercise(self, root, script, status):
        repo, env = prepare(root)
        result = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", script],
            cwd=repo,
            env={**env, "PUBLISH_STATUS": str(status)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, status, result.stderr)
        self.assertTrue(
            (root / "verified").is_file(),
            "push did not authenticate with the test identity",
        )
        socket = (root / "socket").read_text().strip()
        # Resolve relative paths from the actual publishing directory. Probing
        # them from the test runner's cwd would also fail for a live agent.
        followup = subprocess.run(
            ["ssh-add", "-l"],
            cwd=repo,
            capture_output=True,
            env={"PATH": os.environ["PATH"], "SSH_AUTH_SOCK": socket},
        )
        self.assertEqual(followup.returncode, 2, followup.stdout)
        self.assertFalse(os.path.lexists(repo / socket))
        self.assertFalse(
            any(
                env["SSH_KEY"].encode() in p.read_bytes()
                for p in root.rglob("*")
                if p.is_file()
            )
        )
        refs = git(root / "remote", "tag", "--list")
        self.assertEqual(refs, "" if status else "v1.0.0")
        if not status:
            self.assertEqual(
                git(root / "remote", "rev-parse", "v1.0.0^{}"), env["TESTED_SHA"]
            )
