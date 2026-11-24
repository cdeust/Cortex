"""A cancelled tag publisher must revoke its live signing agent before exit."""

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from tests_py.scripts.test_release_credential_lifetime import (
    ENGINES,
    WORKFLOWS,
    prepare,
)


# Pause only after the real OpenSSH agent has signed with the loaded fixture key.
PAUSE = """#!/bin/sh
set -eu
ssh-add -T "$RUNNER_TEMP/identity.pub"
printf '%s\\n' "$SSH_AGENT_PID" "$SSH_AUTH_SOCK" > "$RUNNER_TEMP/starting"
mv "$RUNNER_TEMP/starting" "$RUNNER_TEMP/ready"
exec sleep 60
"""


def await_signature(process, ready):
    # Allow cold process startup separately from the runner's cancellation budget.
    deadline = time.monotonic() + 15
    while not ready.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("publisher did not reach the authenticated pause")
        time.sleep(0.02)
    pid, sock = ready.read_text().splitlines()
    return int(pid), sock


def agent_running(pid):
    # A terminated child can remain as a zombie until the runner's init reaps it.
    status = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True
    ).stdout.strip()
    return bool(status) and not status.startswith("Z")


@unittest.skipIf(os.name == "nt", "the release job uses POSIX signal delivery")
class ReleaseCancellation(unittest.TestCase):
    def test_cancellation_revokes_agent_for_shell_and_group(self):
        for engine in ENGINES:
            steps = yaml.safe_load((WORKFLOWS / engine).read_text())["jobs"]["tag"][
                "steps"
            ]
            script = next(s["run"] for s in steps if s.get("id") == "publish")
            for sig, group in (
                (signal.SIGTERM, False),
                (signal.SIGTERM, True),
                (signal.SIGINT, True),
            ):
                with (
                    self.subTest(engine=engine, sig=sig, group=group),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    self.exercise(Path(tmp), script, sig, group)

    def exercise(self, root, script, sig, group):
        repo, env = prepare(root)
        publisher = root / "python3"
        publisher.write_text(PAUSE)
        publisher.chmod(0o700)
        process = subprocess.Popen(
            ["bash", "-eo", "pipefail", "-c", script],
            cwd=repo,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = None
        try:
            pid, sock = await_signature(process, root / "ready")
            # GitHub's runner grants 2.5 seconds between TERM and KILL.
            deadline = time.monotonic() + 2.5
            (os.killpg if group else os.kill)(process.pid, sig)
            self.assertEqual(process.wait(timeout=2.5), 128 + sig)
            while agent_running(pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(agent_running(pid), "agent survived publisher termination")
            self.assertFalse((repo / sock).exists())
            self.assertTrue((root / "agent-stopped").is_file())
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if pid is not None and agent_running(pid):
                os.kill(pid, signal.SIGTERM)
