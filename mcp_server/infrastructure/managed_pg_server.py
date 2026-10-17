"""Start and stop one managed cluster's postmaster — stdlib only, POSIX.

Invariant: a postmaster is *ours* only when the kernel proves it. The
supervisor that spawns ``bin/postgres -D <cluster> -p <port>`` records
``{pid, started, port}`` (``PgPaths.postmaster``), ``started`` being the
kernel's start time of that PID (``managed_pg_process.started``). A
``postmaster.pid`` names our live postmaster only when its data directory is
this cluster, its PID and port are the recorded ones, the PID is alive as this
user and its start time is the recorded one. A reused PID (any program,
emulated or not), another user's process (EPERM), a dead PID, a foreign
listener on the recorded port: none of them is ours, so none is adopted, and
``stop`` signals nothing. Only after that proof is the port dialled, and the
server must authenticate with this cluster's password
(``managed_pg_protocol``).

Every wait is on a kernel event, never a clock (no ``pg_ctl -w``, whose 60 s
default would decide a slow start failed). The postmaster inherits the write
end of a pipe and ``postmaster.lock`` (an exclusive ``flock``); both pass to
every process it forks. Starting waits until ``postmaster.pid`` reports
``ready`` (PostgreSQL writes that status line once it accepts connections) or
the pipe reaches end of file: the group exited, the failure, whose cause is
what it wrote to ``postgres.log``. Stopping sends SIGINT (fast shutdown) and
blocks on ``postmaster.lock``, granted once the postmaster and all its
children are gone; a supervisor that adopted the postmaster waits the same
way. An adopted postmaster still starting is stopped and started anew. A
``postmaster.pid`` that is not ours is removed before a start (PostgreSQL
would refuse to start over a live PID of this user); one that is ours is
never removed.

source: ADR-1110
source: PostgreSQL src/include/utils/pidfile.h (postmaster.pid lines)
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcp_server.infrastructure import managed_pg as _pg
from mcp_server.infrastructure import managed_pg_process as _process
from mcp_server.infrastructure import managed_pg_protocol as _protocol

# source: pidfile.h LOCK_FILE_LINE_PID 1, _DATA_DIR 2, _PORT 4, _PM_STATUS 8
_PID, _DATA_DIR, _PORT, _STATUS = 0, 1, 3, 7
_READY = "ready"  # source: pidfile.h PM_STATUS_READY ("ready   ")


class ServerError(RuntimeError):
    """The postmaster did not start or stop; the message carries its log."""


@dataclass(frozen=True)
class LockFile:
    """The lines of ``postmaster.pid`` this module reads."""

    pid: int
    data_dir: str
    port: int
    status: str


def read_lockfile(cluster: Path) -> LockFile | None:
    """``postmaster.pid`` as written, ``None`` when absent or not yet whole."""
    try:
        lines = (cluster / "postmaster.pid").read_text(encoding="utf-8").splitlines()
        status = lines[_STATUS].strip() if len(lines) > _STATUS else ""
        return LockFile(int(lines[_PID]), lines[_DATA_DIR], int(lines[_PORT]), status)
    except (FileNotFoundError, ValueError, IndexError):
        return None


def live_postmaster(paths: _pg.PgPaths) -> LockFile | None:
    """This cluster's live postmaster, proven by the kernel; else ``None``. Pure."""
    lock = read_lockfile(paths.cluster)
    if lock is None or Path(lock.data_dir).resolve() != paths.cluster.resolve():
        return None
    record = _pg.read_json(paths.postmaster)
    if record.get("pid") != lock.pid or record.get("port") != lock.port:
        return None
    if not _process.alive_as_this_user(lock.pid):
        return None
    if _process.started(lock.pid) != record.get("started"):
        return None
    return lock


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def _until(cluster: Path, exit_fd: int, done: Callable[[], bool]) -> None:
    """Block until ``done()``, re-evaluated after every kernel event: a change
    in ``cluster``, or the end of file on ``exit_fd`` once the postmaster's
    process group exited. The watch is armed before the first evaluation."""
    watch = _process.watch(cluster, exit_fd)
    try:
        while True:
            watch.follow(cluster / "postmaster.pid")  # before it is read
            if done():
                return
            watch.wait()
    finally:
        watch.close()


def _is_ready(cluster: Path, pid: int) -> bool:
    lock = read_lockfile(cluster)
    return lock is not None and lock.pid == pid and lock.status == _READY


def _prove(paths: _pg.PgPaths, port: int) -> None:
    password = paths.password.read_text(encoding="utf-8").strip()
    _protocol.authenticate(_pg.HOST, port, _pg.USER, password)


def _stop_and_wait(paths: _pg.PgPaths, pid: int) -> None:
    """SIGINT (fast shutdown), then block until ``postmaster.lock`` is granted:
    the postmaster and every process it forked hold it until they exit."""
    os.kill(pid, signal.SIGINT)  # source: PostgreSQL docs, server-shutdown
    group = _pg.open_lock(paths.lock("postmaster"))
    try:
        _pg.flock(group, exclusive=True)
    finally:
        os.close(group)


def _adopt(paths: _pg.PgPaths, lock: LockFile) -> int | None:
    """Our postmaster outlived its supervisor: proven and adopted when ready;
    when still starting (its supervisor died mid-start) it is stopped, and
    ``None`` asks for a fresh start, whose events this supervisor owns."""
    if not _is_ready(paths.cluster, lock.pid):
        _stop_and_wait(paths, lock.pid)
        return None
    _prove(paths, lock.port)
    return lock.port


def _spawn(binaries: Path, paths: _pg.PgPaths) -> tuple[subprocess.Popen, int, int]:
    """``bin/postgres`` as our child, holding ``postmaster.lock`` and the write
    end of the exit pipe; its ``{pid, started, port}`` recorded at once."""
    group = _pg.open_lock(paths.lock("postmaster"))
    if not _pg.flock(group, exclusive=True, blocking=False):
        os.close(group)
        raise ServerError(
            f"a process of an earlier postmaster of {paths.cluster} still runs "
            "(it holds postmaster.lock); stop it, then start Cortex again"
        )
    exit_r, exit_w = os.pipe()
    port = free_port(_pg.HOST)
    log = os.open(paths.server_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    argv = [str(binaries / "postgres"), "-D", str(paths.cluster), "-p", str(port)]
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            pass_fds=(group, exit_w),
        )  # fmt: skip
    finally:
        for fd in (log, group, exit_w):
            os.close(fd)
    record = {"pid": proc.pid, "started": _process.started(proc.pid), "port": port}
    _pg.write_json(paths.postmaster, record)
    return proc, port, exit_r


def _await_ready(
    paths: _pg.PgPaths, proc: subprocess.Popen, exit_r: int, offset: int
) -> None:
    """Ready, or ``ServerError`` with what postgres logged after ``offset``."""
    # The end of file, not waitpid, says the group exited: descriptors close
    # before the process becomes reapable, so poll() can still say "running"
    # after the last event (measured under load, round 4).
    try:
        _until(
            paths.cluster,
            exit_r,
            lambda: _process.exited(exit_r) or _is_ready(paths.cluster, proc.pid),
        )
        gone = _process.exited(exit_r)
    finally:
        os.close(exit_r)
    if not gone:
        return
    proc.wait()  # reapable once its exit completes: the kernel's event
    with paths.server_log.open("rb") as log:
        log.seek(offset)
        output = log.read().decode("utf-8", "replace").strip()
    code = proc.returncode
    raise ServerError(f"postgres exited {code} before it was ready: {output}")


def start(binaries: Path, paths: _pg.PgPaths) -> tuple[int, subprocess.Popen | None]:
    """The port of our ready, proven postmaster, and the process when we spawned it.

    Raises ``ServerError`` with the server's log when it exits before it is
    ready, ``ProtocolError``/``OSError`` when it does not authenticate."""
    lock = live_postmaster(paths)
    port = _adopt(paths, lock) if lock is not None else None
    if port is not None:
        return port, None
    (paths.cluster / "postmaster.pid").unlink(missing_ok=True)  # not ours
    offset = paths.server_log.stat().st_size if paths.server_log.exists() else 0
    proc, port, exit_r = _spawn(binaries, paths)
    _await_ready(paths, proc, exit_r, offset)
    try:
        _prove(paths, port)
    except BaseException:
        _stop_and_wait(paths, proc.pid)
        proc.wait()
        raise
    return port, proc


def stop(paths: _pg.PgPaths, proc: subprocess.Popen | None) -> None:
    """Fast shutdown of our postmaster, waited for; nothing when none is ours."""
    lock = live_postmaster(paths)
    if lock is None:
        return
    _stop_and_wait(paths, lock.pid)
    if proc is not None:
        proc.wait()  # reaps our child, which has exited
