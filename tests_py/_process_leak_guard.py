"""Fail the test session when a process it started is still alive at the end.

INCIDENT (measured by four agents, 2026-10-09): after a run that included
``tests_py/hooks/test_entry.py``, detached ``launcher.py
mcp_server.hooks.ingest_codebase_background`` workers (parent pid 1, working
directory inside the checkout) and their ``mcp-server`` /
``ai-architect-mcp-codebase`` children stayed alive, held the worktree open
and burned CPU on the contributor's machine. Nothing in the suite noticed:
the hook ``Popen``s its worker with ``start_new_session=True``, so no pytest
handle, process group or ``wait`` ever sees it, and once its parent exits it
is re-parented to pid 1, so the process tree cannot find it either.

Mechanism: the session stamps ``CORTEX_TEST_SESSION_TOKEN`` into
``os.environ`` at import time. Every child, detached or not, inherits it
through ``env=dict(os.environ)`` or an implicit environment, and the token is
readable from the process table, which survives re-parenting. At session
teardown the fixture below lists the process table ONCE; any process other
than pytest itself and the ``ps`` that took the snapshot that carries the
token is a leak, and the fixture fails the run listing it. There is no sleep,
timeout or retry: a process that is alive when the snapshot is taken is a
finding, a process that has already exited is not. A test that starts a
process must therefore wait on it (``Popen.wait`` / ``subprocess.run``).

Platform: POSIX only. Reading another process's environment needs ``ps`` with
the environment flag (macOS ``-E``, Linux ``e``); Windows has no equivalent
without psutil or ctypes process-environment walking, and the repo's
no-new-dependencies invariant (scripts/check_no_deps_invariant.py) rules out
psutil. On Windows the guard reports nothing, and that gap is declared, not
hidden.

source: this PR (issue: test_entry leaves detached ingest workers behind)
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

TOKEN_VAR = "CORTEX_TEST_SESSION_TOKEN"

# source: ps(1) on macOS: -E appends the environment to the command column.
# source: procps ps(1) on Linux: the "e" modifier does the same.
_PS_ENV_FLAGS = "-axwwE" if sys.platform == "darwin" else "axwwe"

os.environ[TOKEN_VAR] = uuid.uuid4().hex


def live_tokened_processes(token: str) -> list[tuple[int, str]]:
    """Return (pid, command) of every live process carrying ``token``.

    precondition: ``token`` was exported in the environment of every process
    under test. postcondition: pytest itself and the ``ps`` that took the
    snapshot are excluded; the result is a single point-in-time snapshot of
    the process table (no waiting, no retry). Empty on Windows (see module
    docstring).
    """
    if sys.platform == "win32":
        return []
    ps = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        ["ps", _PS_ENV_FLAGS, "-o", "pid=,command="],
        stdout=subprocess.PIPE,
        text=True,
    )
    out, _ = ps.communicate()
    needle = f"{TOKEN_VAR}={token}"
    found: list[tuple[int, str]] = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if not pid_text.isdigit() or needle not in command:
            continue
        pid = int(pid_text)
        if pid not in (os.getpid(), ps.pid):
            found.append((pid, command.split(needle)[0].strip()))
    return found


@pytest.fixture(scope="session", autouse=True)
def _session_process_leak_guard():
    """Fail the session if any process it spawned outlives it."""
    yield
    leaked = live_tokened_processes(os.environ[TOKEN_VAR])
    if leaked:
        listing = "\n".join(f"  pid {pid}: {cmd[:300]}" for pid, cmd in leaked)
        pytest.fail(
            f"{len(leaked)} process(es) started by this test session are still "
            f"alive at teardown (a test must wait on every process it starts):\n"
            f"{listing}",
            pytrace=False,
        )
