"""The isolated machine and the real Claude Code CLI driven on it — stdlib only.

A fresh HOME and ``CLAUDE_CONFIG_DIR`` under the work directory, a PATH that
holds the ``claude`` binary, a ``python3`` wrapper and the system directories
only, and an environment that inherits nothing Python-, uv- or Cortex-related.
The wrapper records how the host started every plugin process (which
interpreter, whether ``DATABASE_URL`` was set) before handing over to the
real interpreter, under ``arch -x86_64`` for the Rosetta leg.

source: issue #744 (zero-ops install brief, 2026-10-14)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ID = "hypermnesia-mcp@cortex-plugins"  # source: .claude-plugin/marketplace.json
SERVER_NAME = "plugin:hypermnesia-mcp:cortex"  # source: claude mcp list naming
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")  # source: a clean macOS / Linux PATH
CLI_TIMEOUT_SECONDS = 900  # source: measured first launch upper bound, brief step 0

_KEPT_ENV = ("LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL")

_WRAPPER = """#!/bin/sh
# Records each plugin process the host starts, then runs the real interpreter.
if [ -z "${{DATABASE_URL+x}}" ]; then db=unset; elif [ -z "$DATABASE_URL" ]; then db=empty; else db=set; fi
if [ -z "${{CLAUDE_PLUGIN_OPTION_DATABASE_URL+x}}" ]; then opt=unset; elif [ -z "$CLAUDE_PLUGIN_OPTION_DATABASE_URL" ]; then opt=empty; else opt=set; fi
printf '%s\\tDATABASE_URL=%s\\tOPTION=%s\\t%s\\n' "$$" "$db" "$opt" "$*" >> "{log}"
exec {prefix}"{python}" "$@"
"""


@dataclass(frozen=True)
class Machine:
    """One isolated machine: its directories and the environment of every call."""

    work: Path
    home: Path
    project: Path
    debug_log: Path
    spawn_log: Path
    env: dict

    @property
    def config_dir(self) -> Path:
        return self.home / ".claude"

    @property
    def plugin_data(self) -> Path:
        return self.config_dir / "plugins" / "data" / "hypermnesia-mcp-cortex-plugins"


def _claude_binary() -> str:
    found = shutil.which("claude")
    if not found:
        raise SystemExit("install_e2e: the claude CLI is not on PATH")
    return os.path.realpath(found)


def _write_wrapper(bin_dir: Path, python: str, x86_64: bool, log: Path) -> None:
    prefix = "arch -x86_64 " if x86_64 else ""
    wrapper = bin_dir / "python3"
    wrapper.write_text(_WRAPPER.format(log=log, prefix=prefix, python=python))
    wrapper.chmod(0o755)


def build_machine(work: Path, python: str, x86_64: bool) -> Machine:
    """Create the isolated directories, wrapper and environment under ``work``."""
    if work.exists():
        shutil.rmtree(work)
    home, project, bin_dir = work / "home", work / "project", work / "bin"
    for directory in (home, project, bin_dir):
        directory.mkdir(parents=True)
    (bin_dir / "claude").symlink_to(_claude_binary())
    spawn_log = work / "spawns.log"
    _write_wrapper(bin_dir, python, x86_64, spawn_log)
    env = {name: os.environ[name] for name in _KEPT_ENV if name in os.environ}
    env.update(
        HOME=str(home),
        CLAUDE_CONFIG_DIR=str(home / ".claude"),
        PATH=os.pathsep.join((str(bin_dir), *SYSTEM_PATH)),
    )
    return Machine(work, home, project, work / "claude-debug.log", spawn_log, env)


def sandbox_prefix(work: Path) -> list[str]:
    """macOS: deny every TCP connection to port 5432 for the whole run.

    A fresh install must never dial a PostgreSQL it was not configured for;
    on a developer Mac that server may hold someone's real memories.
    """
    if sys.platform != "darwin":
        return []
    profile = work / "no-postgres.sb"
    profile.write_text(
        '(version 1)\n(allow default)\n(deny network-outbound (remote tcp "*:5432"))\n'
    )
    return ["sandbox-exec", "-f", str(profile)]


@dataclass(frozen=True)
class CliResult:
    argv: tuple
    returncode: int
    output: str
    seconds: float


def run_claude(machine: Machine, sandbox: list, *args: str) -> CliResult:
    """Run one ``claude`` command on the machine, stdin closed, output kept."""
    started = time.monotonic()
    done = subprocess.run(
        [*sandbox, "claude", *args],
        cwd=machine.project,
        env=machine.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
    )
    seconds = round(time.monotonic() - started, 2)
    return CliResult(args, done.returncode, done.stdout + done.stderr, seconds)


def start_claude(machine: Machine, sandbox: list, *args: str) -> subprocess.Popen:
    """Start one ``claude`` command without waiting (first-session concurrency)."""
    return subprocess.Popen(
        [*sandbox, "claude", *args],
        cwd=machine.project,
        env=machine.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def finish(proc: subprocess.Popen, args: tuple, started: float) -> CliResult:
    output, _ = proc.communicate(timeout=CLI_TIMEOUT_SECONDS)
    seconds = round(time.monotonic() - started, 2)
    return CliResult(args, proc.returncode, output, seconds)
