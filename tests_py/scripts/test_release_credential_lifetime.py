"""Exercise the release step with Git, a disposable identity and no network."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from itertools import pairwise
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
  *git-upload-pack*) service=git-upload-pack ;;
  *git-receive-pack*) service=git-receive-pack ;;
  *) exit 1 ;;
esac
printf '%s\\n' "$@" > "$RUNNER_TEMP/$service.args"
"$REAL_SSH" -G "$@" > "$RUNNER_TEMP/$service.config"
if test "$service" = git-receive-pack; then
  echo "authenticated push" > "$RUNNER_TEMP/verified"
  test "$PUBLISH_STATUS" = 0 || exit "$PUBLISH_STATUS"
fi
exec "$service" "$RUNNER_TEMP/remote"
"""
# Count attempted agent launches. Refuse an additional daemon before it can
# outlive this fixture, even when a mutated step ignores its exit status.
SSH_AGENT = """#!/bin/sh
set -eu
if test "${1:-}" != -k; then
  echo start >> "$RUNNER_TEMP/agent-starts"
  test "$(wc -l < "$RUNNER_TEMP/agent-starts")" -eq 1 || exit 1
fi
exec "$REAL_AGENT" "$@"
"""


def git(repo, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", repo, *args],
        input=input_text,
        text=True,
        check=True,
        capture_output=True,
    ).stdout.strip()


def bare_repository(root):
    repo = root / "release-repo"
    git(root, "init", "--bare", str(repo))
    git(root, "init", "--bare", str(root / "remote"))
    git(repo, "remote", "add", "origin", "ssh://git@github.com/fixture/repo.git")
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
    return repo, sha


def prepare(root):
    repo, sha = bare_repository(root)
    identity = root / "identity"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", identity], check=True
    )
    key = identity.read_text()
    identity.unlink()
    for name, contents in (("ssh", SSH_TRANSPORT), ("ssh-agent", SSH_AGENT)):
        transport = root / name
        transport.write_text(contents)
        transport.chmod(0o700)
    (root / "github-env").touch()
    env = {
        "HOME": str(root),
        "TMPDIR": str(root),
        "GIT_CONFIG_NOSYSTEM": "1",
        "REAL_SSH": shutil.which("ssh"),
        "REAL_AGENT": shutil.which("ssh-agent"),
        "RUNNER_TEMP": str(root),
        "SSH_KEY": key,
        "TESTED_SHA": sha,
        "RELEASE_TAGS": '["v1.0.0"]',
        "GITHUB_STEP_SUMMARY": str(root / "summary"),
        "GITHUB_ENV": str(root / "github-env"),
        "GIT_SSH_VARIANT": "ssh",
        "PATH": str(root) + os.pathsep + os.environ["PATH"],
    }
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
                    # Linux sockaddr_un.sun_path holds 108 bytes. Even the
                    # parent of this fixture cannot be an absolute socket path.
                    root = Path(tmp) / ("r" * 108)
                    root.mkdir()
                    self.exercise(root, publish["run"], status)

    def exercise(self, root, script, status):
        repo, env = prepare(root)
        (repo / "release-agent.sock").write_text("pre-existing file")
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
        self.check_transport(root)
        self.check_cleanup(root, repo, env)
        refs = git(root / "remote", "tag", "--list")
        self.assertEqual(refs, "" if status else "v1.0.0")
        if not status:
            self.assertEqual(
                git(root / "remote", "rev-parse", "v1.0.0^{}"), env["TESTED_SHA"]
            )

    def check_transport(self, root):
        for service in ("git-upload-pack", "git-receive-pack"):
            args = (root / f"{service}.args").read_text().splitlines()
            self.assertIn(("-F", "/dev/null"), pairwise(args))
            config = (root / f"{service}.config").read_text().splitlines()
            identities = [opt for opt in config if opt.startswith("identityfile ")]
            self.assertEqual(identities, ["identityfile none"])
            for setting in (
                "hostname github.com",
                "user git",
                "identitiesonly no",
                "batchmode yes",
                "stricthostkeychecking true",
                "globalknownhostsfile /dev/null",
                f"userknownhostsfile {root}/release-known-hosts",
            ):
                self.assertIn(setting, config)

    def check_cleanup(self, root, repo, env):
        self.assertEqual((root / "github-env").stat().st_size, 0, "GITHUB_ENV changed")
        self.assertEqual((root / "agent-starts").read_text().splitlines(), ["start"])
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
        self.assertFalse((repo / socket).parent.exists())
        self.assertEqual([p for p in root.rglob("*") if p.is_socket()], [])
        self.assertEqual((repo / "release-agent.sock").read_text(), "pre-existing file")
        self.assertFalse(
            any(
                env["SSH_KEY"].encode() in p.read_bytes()
                for p in root.rglob("*")
                if p.is_file()
            )
        )
