"""Fixture that runs the real "Publish declared package tags" step with native OpenSSH.

The step body is read from each Pipeline engine and executed as actions/runner runs
`shell: bash` (bash --noprofile --norc -eo pipefail {0}), from the bare release
repository. Git publishes through its real ssh:// transport into a local receiver; a
stand-in `ssh` records what the client was given, has the agent sign, and serves the
Git command. Only a fixture key generated here is ever loaded.

RELEASE_CREDENTIAL_WORKFLOWS (paths joined by os.pathsep) replaces the two workflows,
so the same proof runs against another revision or a mutant.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

from tests_py.scripts._release_step_texts import (
    AGENT_WRAPPER,
    HOSTILE_SSH_CONFIG,
    IGNORE_TERM,
    SSH_WRAPPER,
)

_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = tuple(
    Path(p)
    for p in os.environ.get("RELEASE_CREDENTIAL_WORKFLOWS", "").split(os.pathsep)
    if p
) or tuple(
    _ROOT / ".github/workflows" / n for n in ("pipeline.yml", "pipeline-post-merge.yml")
)
STEP = "Publish declared package tags"
TAG = "v0.0.0-fixture"
# source: sys/un.h sun_path: 104 bytes on macOS, 108 on Linux, NUL included.
SUN_PATH_BYTES = 104
# source: actions/runner@1060fd3 src/Runner.Sdk/ProcessInvoker.cs lines 32-33, 443-464:
# SIGINT to the step PID, SIGTERM 7.5 s later, process tree killed 2.5 s after that.
RUNNER_SIGINT_WINDOW_S = 7.5
# source: same ProcessInvoker.cs lines: the tree kill follows SIGTERM by 2.5 s.
RUNNER_SIGTERM_WINDOW_S = 2.5
# source: a real ssh client ends on EOF once Git is gone; one second covers scheduling.
TRANSPORT_EXIT_S = 1.0
# source: openssh-portable ssh-agent.c, parent_alive_interval = 10 for a command agent.
OPENSSH_PARENT_CHECK_S = 10


def alive(pid):
    """A zombie has released its memory, sockets and keys: it is not alive."""
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    )
    state = out.stdout.strip()
    return out.returncode == 0 and state != "" and not state.startswith("Z")


def processes():
    rows = subprocess.run(
        ["ps", "-Ao", "pid=,ppid=,stat=,args="],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [row.split(None, 3) for row in rows if len(row.split(None, 3)) == 4]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def step_section(text):
    return text.split("      - name: " + STEP + "\n", 1)[1].split("\n      - ", 1)[0]


def publish_body(path):
    return textwrap.dedent(
        step_section(path.read_text()).split("        run: |\n", 1)[1]
    )


def kill(pid, sig=signal.SIGKILL):
    try:
        os.kill(int(pid), sig)
    except (ProcessLookupError, ValueError):
        pass


class Fixture:
    def __init__(self, root, body, key=None):
        self.root = root
        # The step's TMPDIR holds the agent socket; sun_path forbids a deep directory.
        self.socket_base = Path(tempfile.mkdtemp(prefix="rc", dir="/tmp"))
        self.log = root / "log"
        self.log.mkdir()
        self._identity()
        # A space in RUNNER_TEMP proves the known-hosts path survives ssh's own parsing.
        self.runner_temp = root / "runner temp"
        self.runner_temp.mkdir()
        host_key = self.public.read_text().split(" ", 2)[:2]
        (self.runner_temp / "release-known-hosts").write_text(
            "github.invalid " + " ".join(host_key) + "\n"
        )
        self._repositories()
        self.commands = {
            n: root / n for n in ("github-env", "github-output", "github-path")
        }
        for path in self.commands.values():
            path.touch()
        self.script = root / "step.sh"
        self.script.write_text(body)
        self.env = self._environment(self.private if key is None else key)
        self.runner_entries = set(os.listdir(self.runner_temp))
        self.process = None

    def _identity(self):
        keys = self.root / "keys"
        keys.mkdir()
        subprocess.run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "fixture",
                "-f",
                keys / "id",
            ],
            check=True,
        )
        self.private = (keys / "id").read_text()
        (keys / "id").unlink()
        self.secret_body = self.private.splitlines()[1]
        self.public = keys / "id.pub"

    def _repositories(self):
        work = self.root / "work"
        git("init", "-q", str(work))
        (work / "file").write_text("release fixture\n")
        git("-C", str(work), "add", "file")
        git(
            "-C",
            str(work),
            "-c",
            "user.name=f",
            "-c",
            "user.email=f@f",
            "commit",
            "-q",
            "-m",
            "f",
        )
        self.sha = git("-C", str(work), "rev-parse", "HEAD").stdout.strip()
        self.remote = self.root / "remote.git"
        git("init", "-q", "--bare", str(self.remote))
        self.repo = self.runner_temp / "release-repo"
        git("init", "-q", "--bare", str(self.repo))
        git("-C", str(self.repo), "fetch", "-q", str(work), self.sha)
        url = "ssh://git@github.invalid" + str(self.remote)
        git("-C", str(self.repo), "remote", "add", "origin", url)

    def _environment(self, key):
        home = self.root / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "config").write_text(HOSTILE_SSH_CONFIG)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, text in (("ssh", SSH_WRAPPER), ("ssh-agent", AGENT_WRAPPER)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o700)
        return {
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "HOME": str(home),
            "FIXTURE_HOSTILE_CONFIG": str(home / ".ssh" / "config"),
            "TMPDIR": str(self.socket_base),
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "RUNNER_TEMP": str(self.runner_temp),
            "SSH_KEY": key,
            "RELEASE_TAGS": '["' + TAG + '"]',
            "TESTED_SHA": self.sha,
            "GITHUB_ENV": str(self.commands["github-env"]),
            "GITHUB_OUTPUT": str(self.commands["github-output"]),
            "GITHUB_PATH": str(self.commands["github-path"]),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "FIXTURE_LOG": str(self.log),
            "FIXTURE_PUBLIC_KEY": str(self.public),
            "FIXTURE_REAL_SSH": shutil.which("ssh"),
            "FIXTURE_REAL_AGENT": shutil.which("ssh-agent"),
        }

    def publisher_ignores_sigterm(self):
        hook = self.root / "python-hook"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(IGNORE_TERM)
        self.env["PYTHONPATH"] = str(hook)

    def start(self, block=False):
        env = dict(self.env, **({"FIXTURE_BLOCK": "1"} if block else {}))
        command = ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(self.script)]
        self.process = subprocess.Popen(
            command,
            cwd=self.repo,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return self.process

    def finish(self, timeout=60):
        output, _ = self.process.communicate(timeout=timeout)
        return self.process.returncode, output

    def transports(self):
        result = []
        for env_file in sorted(self.log.glob("ssh.*.env")):
            record = dict(
                line.split("=", 1) for line in env_file.read_text().splitlines()
            )
            config = (
                Path(str(env_file)[: -len(".env")] + ".config").read_text().splitlines()
            )
            record["config"] = {
                k: v for k, _, v in (line.partition(" ") for line in config)
            }
            result.append(record)
        return result

    def wait_ready(self, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if list(self.log.glob("ssh.*.ready")):  # written after the .env record
                return self.transports()[0]
            if self.process.poll() is not None:
                raise AssertionError(
                    "step ended before its transport: " + self.process.stdout.read()
                )
            time.sleep(0.05)
        raise AssertionError("transport never started")

    def publisher(self, agent):
        """The Python publisher: the step shell's one live child besides the agent."""
        found = [
            int(pid)
            for pid, ppid, stat, _ in processes()
            if ppid == str(self.process.pid)
            and pid != agent
            and not stat.startswith("Z")
        ]
        if len(found) != 1:
            raise AssertionError("expected one publisher under the step: %r" % found)
        return found[0]

    def remote_tag(self):
        out = subprocess.run(
            [
                "git",
                "--git-dir",
                str(self.remote),
                "rev-parse",
                "--verify",
                "-q",
                "refs/tags/" + TAG + "^{}",
            ],
            capture_output=True,
            text=True,
        )
        return out.stdout.strip() or None

    def owns(self, args):
        return str(self.root) in args or str(self.socket_base) in args

    def cleanup(self):
        """Play the runner's final tree kill, then remove every agent started."""
        if self.process is not None:
            kill(-self.process.pid)
            self.process.stdout.close()
        agents = [r["agent"] for r in self.transports() if r.get("agent")]
        if (self.log / "agent-pid").exists():
            agents.append((self.log / "agent-pid").read_text())
        for pid in agents:
            kill(pid)
        for record in self.transports():
            directory = (self.repo / record["socket"]).parent
            if record["socket"] and directory.name.startswith("release-agent."):
                shutil.rmtree(directory, ignore_errors=True)
        for pid, _, _, args in processes():
            if self.owns(args) and int(pid) != os.getpid():
                kill(pid)
