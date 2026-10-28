"""The isolated machine and the real Claude Code CLI driven on it — stdlib only.

A fresh HOME and ``CLAUDE_CONFIG_DIR`` under the work directory and no inherited
Python, uv or Cortex settings. POSIX uses a recording python3 wrapper and system
PATH; Windows preserves its system PATH and uses a private native python3.exe.
Claude's installed executable (or npm package entrypoint) is called directly.
The POSIX wrapper records how the host started plugin processes before handing
over to the real interpreter, under ``arch -x86_64`` for the Rosetta leg.

source: issue #744 (zero-ops install brief, 2026-10-14)
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ID = "hypermnesia-mcp@cortex-plugins"  # source: .claude-plugin/marketplace.json
SERVER_NAME = "plugin:hypermnesia-mcp:cortex"  # source: claude mcp list naming
SYSTEM_PATH = (
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)  # source: a clean macOS / Linux PATH
CLI_TIMEOUT_SECONDS = 900  # source: measured first launch upper bound, brief step 0

_KEPT_ENV = (
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "USER",
    "LOGNAME",
    "SHELL",
    "USERNAME",
    "USERDOMAIN",
)

_WRAPPER = """#!/bin/sh
# Records each plugin process the host starts, then runs the real interpreter.
state() {{ eval "set=\\${{$1+x}} value=\\${{$1-}}"; if [ -z "$set" ]; then echo unset;
  elif [ -z "$value" ]; then echo empty; else echo set; fi; }}
db=$(state DATABASE_URL); opt=$(state CLAUDE_PLUGIN_OPTION_DATABASE_URL)
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
    cli: tuple[str, ...]

    @property
    def config_dir(self) -> Path:
        return self.home / ".claude"

    @property
    def server_log(self) -> Path:
        return self.work / "mcp-server.stderr"

    @property
    def plugin_data(self) -> Path:
        return self.config_dir / "plugins" / "data" / "hypermnesia-mcp-cortex-plugins"


def _claude_command() -> tuple[str, ...]:
    found = shutil.which("claude")
    if not found:
        raise SystemExit("install_e2e: the claude CLI is not on PATH")
    executable = Path(found).resolve()
    if executable.suffix.lower() != ".cmd":
        return (str(executable),)
    # Resolve npm's declared bin instead of executing the .cmd shim. The pinned
    # 2.1.306 package declares bin/claude.exe; older JS packages require Node.
    # source: npm view @anthropic-ai/claude-code@2.1.306 bin --json
    # npm Windows global shims live in prefix; local shims in node_modules/.bin.
    # source: https://docs.npmjs.com/cli/v11/configuring-npm/folders#executables
    directory = executable.parent
    modules = directory / "node_modules"
    if (
        directory.name.casefold() == ".bin"
        and directory.parent.name.casefold() == "node_modules"
    ):
        modules = directory.parent
    package = modules / "@anthropic-ai/claude-code"
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    entry = (package / manifest["bin"]["claude"]).resolve()
    if not entry.is_relative_to(package.resolve()) or not entry.is_file():
        raise RuntimeError("Claude npm entrypoint is outside its installed package")
    if entry.suffix.lower() == ".exe":
        return (str(entry),)
    node = executable.parent / "node.exe"
    selected = str(node) if node.is_file() else shutil.which("node")
    if not selected:
        raise RuntimeError("Claude npm installation requires Node on PATH")
    return (selected, str(entry))


def _windows_python(work: Path, python: str) -> Path:
    # A native executable alias works both in Git Bash hooks and CreateProcess
    # stdio launches; a .sh/.cmd wrapper does not implement that same contract.
    # https://docs.python.org/3/library/venv.html
    runtime = work / "runtime"
    subprocess.run([python, "-m", "venv", "--without-pip", str(runtime)], check=True)
    scripts = runtime / "Scripts"
    shutil.copy2(scripts / "python.exe", scripts / "python3.exe")
    return scripts


def _machine_environment(home: Path, bin_dir: Path, *, windows: bool) -> dict:
    kept = (*_KEPT_ENV, "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
    env = {name: os.environ[name] for name in kept if name in os.environ}
    path = os.environ.get("PATH", "") if windows else os.pathsep.join(SYSTEM_PATH)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        CLAUDE_CONFIG_DIR=str(home / ".claude"),
        PYTHONUTF8="1",
        PATH=os.pathsep.join((str(bin_dir), path)),
    )
    if windows:
        for name in ("APPDATA", "LOCALAPPDATA"):
            directory = home / name.lower()
            directory.mkdir()
            env[name] = str(directory)
    return env


def _write_wrapper(bin_dir: Path, python: str, x86_64: bool, log: Path) -> None:
    prefix = "arch -x86_64 " if x86_64 else ""
    wrapper = bin_dir / "python3"
    wrapper.write_text(_WRAPPER.format(log=log, prefix=prefix, python=python))
    wrapper.chmod(0o755)


def build_machine(work: Path, python: str, x86_64: bool) -> Machine:
    """Create the isolated directories, wrapper and environment under ``work``."""
    # Refuse an existing tree rather than deleting arbitrary caller data.
    work.mkdir(parents=True, exist_ok=False)
    home, project, bin_dir = work / "home", work / "project", work / "bin"
    for directory in (home, project, bin_dir):
        directory.mkdir()
    cli = _claude_command()
    spawn_log = work / "spawns.log"
    if os.name == "nt":
        if x86_64:
            raise ValueError("Rosetta execution is only supported on macOS")
        bin_dir = _windows_python(work, python)
    else:
        _write_wrapper(bin_dir, python, x86_64, spawn_log)
    env = _machine_environment(home, bin_dir, windows=os.name == "nt")
    return Machine(work, home, project, work / "claude-debug.log", spawn_log, env, cli)


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
        [*sandbox, *machine.cli, *args],
        cwd=machine.project,
        env=machine.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
    )
    seconds = round(time.monotonic() - started, 2)
    return CliResult(args, done.returncode, done.stdout + done.stderr, seconds)


def start_claude(machine: Machine, sandbox: list, *args: str) -> subprocess.Popen:
    """Start one ``claude`` command without waiting (first-session concurrency)."""
    return subprocess.Popen(
        [*sandbox, *machine.cli, *args],
        cwd=machine.project,
        env=machine.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )


def finish(proc: subprocess.Popen, args: tuple, started: float) -> CliResult:
    output, _ = proc.communicate(timeout=CLI_TIMEOUT_SECONDS)
    seconds = round(time.monotonic() - started, 2)
    return CliResult(args, proc.returncode, output, seconds)
