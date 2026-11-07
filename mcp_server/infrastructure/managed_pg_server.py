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

The one other process ever dialled is the proven writer of a ``ready``
``postmaster.pid`` (``managed_pg_pidfile.written_by``: its kernel start time
is the file's line 3) while a group nothing recorded holds
``postmaster.lock`` (a 0600 file in the 0700 root, the boundary that guards
``postmaster.json`` too): a postmaster whose supervisor died between spawning
and recording it. It is adopted and recorded only if it authenticates with
the cluster's password; otherwise the start fails naming its PID and port,
and it is neither signalled nor its ``postmaster.pid`` touched.

Every wait is on a kernel event, never a clock (no ``pg_ctl -w``, whose 60 s
default would decide a slow start failed). The postmaster inherits the write
end of a pipe and ``postmaster.lock``; both pass to every process it forks.
Starting waits until ``postmaster.pid`` reports ``ready`` (PostgreSQL writes
that status line once it accepts connections) or the pipe reaches end of
file: the group exited, the failure, whose cause is what it wrote to
``postgres.log``. Stopping sends SIGINT (fast shutdown) and blocks on
``postmaster.lock``, granted once the postmaster and all its children are
gone. An adopted postmaster still starting is stopped and started anew.
``postmaster.pid`` is removed only while this process holds
``postmaster.lock`` (no postmaster Cortex started is alive) and the file is
proven stale. A live writer Cortex did not start holds no lock: it is named
and left alone, never adopted (no exit event to supervise or stop on).

source: ADR-1114
source: PostgreSQL src/include/utils/pidfile.h (postmaster.pid lines)
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from pathlib import Path
from typing import Callable

from mcp_server.infrastructure import managed_pg as _pg
from mcp_server.infrastructure import managed_pg_process as _process
from mcp_server.infrastructure import managed_pg_protocol as _protocol
from mcp_server.infrastructure.managed_pg_pidfile import (
    READY,
    LockFile,
    live_postmaster,
    read_lockfile,
    ready,
    written_by,
)


class ServerError(RuntimeError):
    """The postmaster did not start or stop; the message carries its log."""


def free_port(host: str, preferred: int | None = None) -> int:
    """``preferred`` when it can be bound now (with ``SO_REUSEADDR``, as
    PostgreSQL binds), else any free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, preferred or 0))
        except OSError:
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
    return lock is not None and lock.pid == pid and lock.status == READY


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


def _recover_unrecorded(paths: _pg.PgPaths) -> int | None:
    """``postmaster.lock`` is held by a group nothing recorded: wait until it
    is gone (``None``) or ready, then adopt it only if it proves itself."""
    gone_r = _process.released(paths.lock("postmaster"))
    try:
        _until(
            paths.cluster,
            gone_r,
            lambda: _process.exited(gone_r) or ready(paths.cluster) is not None,
        )
        gone = _process.exited(gone_r)
    finally:
        os.close(gone_r)
    lock = None if gone else ready(paths.cluster)
    if lock is None:
        return None
    try:
        _prove(paths, lock.port)
    except (_protocol.ProtocolError, OSError) as exc:
        raise ServerError(
            f"pid {lock.pid} on port {lock.port} holds postmaster.lock of "
            f"{paths.cluster} but did not authenticate with the cluster's "
            f"password ({exc}); it was not adopted, signalled or removed: stop "
            "it, then start Cortex again"
        ) from exc
    record = {"pid": lock.pid, "started": _process.started(lock.pid), "port": lock.port}
    _pg.write_json(paths.postmaster, record)
    return lock.port


def _spawn(
    binaries: Path, paths: _pg.PgPaths, group: int, preferred: int | None
) -> tuple[subprocess.Popen, int, int]:
    """``bin/postgres`` as our child, holding ``postmaster.lock`` (``group``,
    locked) and the write end of the exit pipe; ``{pid, started, port}``
    recorded at once."""
    exit_r, exit_w = os.pipe()
    port = free_port(_pg.HOST, preferred)
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


def _existing(paths: _pg.PgPaths) -> tuple[bool, int]:
    """``(True, port)`` for a postmaster of this cluster already running,
    adopted; else ``(False, fd)`` with ``postmaster.lock`` held by ``fd``."""
    lock = live_postmaster(paths)
    port = _adopt(paths, lock) if lock is not None else None
    while port is None:
        group = _pg.open_lock(paths.lock("postmaster"))
        if _pg.flock(group, exclusive=True, blocking=False):
            return False, group
        os.close(group)
        port = _recover_unrecorded(paths)  # None once that group is gone
    return True, port


def _remove_stale_pid_file(paths: _pg.PgPaths, group: int) -> None:
    """Remove ``postmaster.pid`` only when proven stale. A live writer is a
    postmaster of this cluster that Cortex did not start (it holds no
    ``postmaster.lock``): it is named and left alone, never adopted (no lock
    means no exit event to supervise or to stop on)."""
    lock = read_lockfile(paths.cluster)
    if lock is not None and written_by(lock):
        os.close(group)
        raise ServerError(
            f"pid {lock.pid} on port {lock.port} is a live postmaster of "
            f"{paths.cluster} that Cortex did not start (its start time is the "
            "one postmaster.pid records); nothing was removed or signalled: stop "
            f"it (pg_ctl -D {paths.cluster} stop), then start Cortex again"
        )
    (paths.cluster / "postmaster.pid").unlink(missing_ok=True)  # proven stale


def start(
    binaries: Path, paths: _pg.PgPaths, preferred: int | None = None
) -> tuple[int, subprocess.Popen | None]:
    """The port of our ready, proven postmaster, and the process when we
    spawned it (on ``preferred`` when that port is free).

    Raises ``ServerError`` with the server's log when it exits before it is
    ready, ``ProtocolError``/``OSError`` when it does not authenticate."""
    adopted, value = _existing(paths)
    if adopted:
        return value, None
    group = value
    _remove_stale_pid_file(paths, group)
    offset = paths.server_log.stat().st_size if paths.server_log.exists() else 0
    proc, port, exit_r = _spawn(binaries, paths, group, preferred)
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
