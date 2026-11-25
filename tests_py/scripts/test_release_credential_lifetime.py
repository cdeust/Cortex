"""Native proof that the release write key lives only inside its publish step.

A probe that reports "agent gone" proves nothing unless the same probe first reached
the live agent: ssh-add -l also answers 2 when the socket path exceeds sun_path. Every
lifetime assertion is therefore paired with a positive control the transport took, on
the same socket path and from the same directory, while the agent was alive.

The bounds are the runner's (see _release_step_fixture): success, rejection, an
unusable key, SIGINT, SIGTERM, a second signal, an agent or a publisher that no longer
reacts to SIGTERM, and SIGKILL of the step shell.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests_py.scripts import _release_step_fixture as rs


@unittest.skipIf(os.name == "nt", "the tag job runs on Ubuntu with POSIX OpenSSH")
class ReleaseCredentialLifetime(unittest.TestCase):
    def fixture(self, path, key=None):
        temp = Path(tempfile.mkdtemp(prefix="rc"))
        self.addCleanup(shutil.rmtree, temp, True)
        fixture = rs.Fixture(temp, rs.publish_body(path), key)
        self.addCleanup(shutil.rmtree, fixture.socket_base, True)
        self.addCleanup(fixture.cleanup)
        return fixture

    def each_workflow(self, check):
        for path in rs.WORKFLOWS:
            with self.subTest(workflow=str(path)):
                check(path)

    def assert_released(self, fixture):
        """Nothing that could still use the key outlives the step."""
        starts = (fixture.log / "agent-starts").read_text().splitlines()
        starts = [
            first for first in starts if first != "-k"
        ]  # ssh-agent -k starts none
        self.assertEqual(
            len(starts), 1, "exactly one signing agent is started: %r" % starts
        )
        for record in fixture.transports():
            self.assert_agent_gone(fixture, record)
            self.assert_transport_gone(record)
        leftovers = [
            r for r in rs.processes() if not r[2].startswith("Z") and fixture.owns(r[3])
        ]
        self.assertEqual(leftovers, [], "a process of the step outlived it")
        self.assertEqual(set(os.listdir(fixture.runner_temp)), fixture.runner_entries)
        self.assertEqual(
            os.listdir(fixture.socket_base), [], "the step left files in TMPDIR"
        )
        for name, path in fixture.commands.items():
            self.assertEqual(
                path.read_text(), "", name + " must not carry anything from this step"
            )
        for path in fixture.root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                self.assertNotIn(
                    fixture.secret_body.encode(), path.read_bytes(), str(path)
                )

    def assert_agent_gone(self, fixture, record):
        self.assertEqual(
            record["list"], "0", "positive control: the transport reached the agent"
        )
        socket = (
            fixture.repo / record["socket"]
        )  # a relative path resolves from the step
        self.assertLess(len(record["socket"].encode()), rs.SUN_PATH_BYTES)
        self.assertNotIn(
            socket.parent,
            (fixture.repo, fixture.runner_temp),
            "the socket lives in a directory created for it alone",
        )
        self.assertFalse(
            rs.alive(record["agent"]), "the signing agent outlived the step"
        )
        self.assertFalse(socket.exists(), "the agent socket outlived the step")
        self.assertFalse(
            socket.parent.exists(), "the socket directory outlived the step"
        )
        probe = subprocess.run(
            ["ssh-add", "-l"],
            cwd=fixture.repo,
            capture_output=True,
            env=dict(fixture.env, SSH_AUTH_SOCK=record["socket"]),
        )
        self.assertEqual(
            probe.returncode, 2, "the probe that reached the agent no longer does"
        )

    def assert_transport_gone(self, record):
        deadline = time.monotonic() + rs.TRANSPORT_EXIT_S
        for pid in (record["pid"], record["parent"]):
            while rs.alive(pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(rs.alive(pid), "git or its ssh client outlived the step")

    def assert_transport_isolated(self, record, fixture):
        config = record["config"]
        self.assertEqual(
            record["key_in_environment"], "", "the raw key reached the transport"
        )
        self.assertEqual(
            record["signed"], "0", "the agent signs with the release identity"
        )
        self.assertEqual(config.get("identityfile"), "none")
        self.assertEqual(config.get("identitiesonly"), "no")
        self.assertEqual(config.get("batchmode"), "yes")
        self.assertEqual(config.get("stricthostkeychecking"), "true")
        self.assertEqual(config.get("globalknownhostsfile"), "/dev/null")
        known = str(fixture.runner_temp / "release-known-hosts")
        self.assertEqual(config.get("userknownhostsfile"), known)
        self.assertNotIn("proxycommand", config, "the host's ssh configuration applied")

    def test_success_publishes_through_git_ssh_and_releases_the_key(self):
        def check(path):
            fixture = self.fixture(path)
            fixture.start()
            status, output = fixture.finish()
            self.assertEqual(status, 0, output)
            self.assertEqual(fixture.remote_tag(), fixture.sha, output)
            self.assertTrue(
                fixture.transports(), "Git never ran the configured transport"
            )
            for record in fixture.transports():
                self.assert_transport_isolated(record, fixture)
            self.assert_released(fixture)

        self.each_workflow(check)

    def test_rejected_push_fails_and_releases_the_key(self):
        def check(path):
            fixture = self.fixture(path)
            hook = fixture.remote / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\necho refused by fixture >&2\nexit 1\n")
            hook.chmod(0o700)
            fixture.start()
            status, output = fixture.finish()
            self.assertEqual(status, 1, output)
            self.assertIsNone(fixture.remote_tag())
            self.assertTrue(fixture.transports(), output)
            self.assert_released(fixture)

        self.each_workflow(check)

    def test_unusable_key_fails_before_any_transport(self):
        def check(path):
            fixture = self.fixture(path, key="not a private key\n")
            fixture.start()
            status, output = fixture.finish()
            self.assertNotEqual(status, 0, output)
            self.assertEqual(fixture.transports(), [], output)
            self.assert_released(fixture)
            self.assertEqual(os.listdir(fixture.socket_base), [])

        self.each_workflow(check)

    def cancel(self, path, signals, window, expected):
        fixture = self.fixture(path)
        fixture.start(block=True)
        fixture.wait_ready()
        for sig in signals:  # the runner signals the step PID, not its group
            os.kill(fixture.process.pid, sig)
            time.sleep(0.05)
        try:
            status, output = fixture.finish(timeout=window)
        except subprocess.TimeoutExpired:
            self.fail(
                "the step did not stop within the runner's %.1f s window" % window
            )
        self.assertEqual(status, expected, output)
        self.assertIsNone(fixture.remote_tag())
        self.assert_released(fixture)

    def test_runner_sigint_releases_the_key_within_its_window(self):
        self.each_workflow(
            lambda p: self.cancel(
                p, [signal.SIGINT], rs.RUNNER_SIGINT_WINDOW_S, 128 + signal.SIGINT
            )
        )

    def test_sigterm_releases_the_key_within_the_runner_window(self):
        self.each_workflow(
            lambda p: self.cancel(
                p, [signal.SIGTERM], rs.RUNNER_SIGTERM_WINDOW_S, 128 + signal.SIGTERM
            )
        )

    def test_second_signal_during_release_does_not_cut_it_short(self):
        """The runner follows SIGINT with SIGTERM; a terminal may send two SIGINTs."""
        self.each_workflow(
            lambda p: self.cancel(
                p,
                [signal.SIGINT, signal.SIGTERM],
                rs.RUNNER_SIGINT_WINDOW_S,
                128 + signal.SIGINT,
            )
        )

    def test_agent_that_ignores_sigterm_is_killed_and_fails_the_step(self):
        def check(path):
            fixture = self.fixture(path)
            hook = fixture.remote / "hooks" / "pre-receive"
            # A stopped agent cannot act on SIGTERM; SIGKILL still ends it.
            hook.write_text(
                '#!/bin/sh\nkill -STOP "$(cat "$FIXTURE_LOG/agent-pid")"\nexit 0\n'
            )
            hook.chmod(0o700)
            fixture.env["FIXTURE_RECORD_AGENT"] = "1"
            started = time.monotonic()
            fixture.start()
            status, output = fixture.finish()
            self.assertLess(time.monotonic() - started, rs.RUNNER_SIGINT_WINDOW_S)
            self.assertEqual(status, 1, output)
            self.assertIn("::error::the signing agent did not stop on SIGTERM", output)
            self.assert_released(fixture)

        self.each_workflow(check)

    def stop_publisher(self, path, disable, expected):
        fixture = self.fixture(path)
        if disable is None:
            fixture.publisher_ignores_sigterm()
        fixture.start(block=True)
        record = fixture.wait_ready()
        self.assertEqual(record["list"], "0")
        if disable is not None:
            os.kill(fixture.publisher(record["agent"]), disable)
        os.kill(fixture.process.pid, signal.SIGINT)
        try:
            status, output = fixture.finish(timeout=rs.RUNNER_SIGINT_WINDOW_S)
        except subprocess.TimeoutExpired:
            self.fail("the publisher held the step past the runner's window")
        self.assertEqual(status, expected, output)
        if expected == 1:
            self.assertIn("::error::the publisher did not stop on SIGTERM", output)
        self.assert_released(fixture)

    def test_publisher_that_ignores_sigterm_is_killed_with_git_and_ssh(self):
        """A publisher deaf to SIGTERM must not hold the release nor leave Git."""
        self.each_workflow(lambda p: self.stop_publisher(p, None, 1))

    def test_stopped_publisher_is_released_with_git_and_ssh(self):
        self.each_workflow(
            lambda p: self.stop_publisher(p, signal.SIGSTOP, 128 + signal.SIGINT)
        )

    def test_killed_step_leaves_an_agent_that_stops_by_itself(self):
        """No step code runs after SIGKILL: the agent is bound to the step command."""

        def check(path):
            fixture = self.fixture(path)
            fixture.start(block=True)
            record = fixture.wait_ready()
            self.assertEqual(record["list"], "0")
            os.kill(fixture.process.pid, signal.SIGKILL)
            # The runner kills the remaining tree afterwards (fixture.cleanup plays
            # that part); only the agent, which holds the key, must not wait for it.
            fixture.process.wait(timeout=5)
            deadline = time.monotonic() + rs.OPENSSH_PARENT_CHECK_S + 2
            while rs.alive(record["agent"]) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(
                rs.alive(record["agent"]), "the agent kept the key after SIGKILL"
            )
            probe = subprocess.run(
                ["ssh-add", "-l"],
                cwd=fixture.repo,
                capture_output=True,
                env=dict(fixture.env, SSH_AUTH_SOCK=record["socket"]),
            )
            self.assertEqual(probe.returncode, 2)

        self.each_workflow(check)


if __name__ == "__main__":
    unittest.main()
