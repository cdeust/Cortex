"""managed_pg_server: a postmaster is ours only when the kernel proves it.

PR #748's round-3 review: blocker B2 — "some live PID of this user + some
listener on the recorded port" was adopted as this cluster's postmaster, and
``stop()`` ran ``pg_ctl stop`` against it (foreign.py, stopprobe.py). N3 —
the PermissionError mutant survived because the port fallback masked it.
Here ``(pid, kernel start time, port)`` recorded at spawn is the identity; a
foreign process and its listener are never dialled, adopted or signalled.
D2 — readiness and exit are kernel events, no ``pg_ctl -w`` timer.

source: ADR-1114
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_server.infrastructure import managed_pg_pidfile as pidfile
from tests_py._hermetic_hook_env import wait_for_process_exit
from tests_py.infrastructure import fake_postgres
from tests_py.infrastructure.fake_pg_lifeline import fake_pg_lifeline

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX only (ADR-1114)")
__all__ = ["fake_pg_lifeline"]  # the autouse fixture, imported
HOST = "127.0.0.1"  # source: managed_pg.HOST
# source: test helper (a live process of this user listening on loopback that
# reports every connection it is offered and every SIGINT it receives; the
# handler is explicit, so a SIGINT inherited as ignored is still observed)
_FOREIGN = (
    "import signal, socket, sys, threading\n"
    "signal.signal(signal.SIGINT, lambda *a: print('signalled', flush=True))\n"
    "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
    "print(s.getsockname()[1], flush=True)\n"
    "def serve():\n"
    "    while True:\n"
    "        c, _ = s.accept(); print('dialled', flush=True); c.close()\n"
    "threading.Thread(target=serve, daemon=True).start()\n"
    "sys.stdin.read()\n"
)


@pytest.fixture
def pg(tmp_path):
    from mcp_server.infrastructure import managed_pg, managed_pg_server

    paths = managed_pg.PgPaths(tmp_path / "root")
    paths.cluster.mkdir(parents=True)
    paths.password.write_text("secret\n")
    return managed_pg, managed_pg_server, paths


@pytest.fixture
def foreign():
    started: list[subprocess.Popen] = []

    def spawn() -> tuple[subprocess.Popen, int]:
        proc = subprocess.Popen(
            [sys.executable, "-c", _FOREIGN],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        started.append(proc)
        return proc, int(proc.stdout.readline())

    yield spawn
    for proc in started:
        proc.stdin.close()
        proc.wait()


def _pid_file(paths, pid: int, port: int, data_dir: Path | None = None) -> None:
    data_dir = paths.cluster if data_dir is None else data_dir
    lines = f"{pid}\n{data_dir}\n0\n{port}\n\n{HOST}\n1 2\nready   \n"
    (paths.cluster / "postmaster.pid").write_text(lines)


def _record(pg, pid: int, port: int, started: str | None = None) -> None:
    managed_pg, _server, paths = pg
    from mcp_server.infrastructure import managed_pg_process

    started = managed_pg_process.started(pid) if started is None else started
    record = {"pid": pid, "started": started, "port": port}
    managed_pg.write_json(paths.postmaster, record)


def _dialled(proc: subprocess.Popen) -> list[str]:
    proc.stdin.close()
    lines = proc.stdout.read().split()
    proc.wait()
    return lines


def test_a_recorded_live_postmaster_is_ours(pg, foreign):
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    _record(pg, proc.pid, port)
    assert pidfile.live_postmaster(paths).pid == proc.pid


def test_a_reused_pid_with_a_listener_is_not_ours(pg, foreign):
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    _record(pg, proc.pid, port, started="1.000000")  # the pid's earlier owner
    assert pidfile.live_postmaster(paths) is None


def test_an_unrecorded_pid_with_a_listener_is_not_ours(pg, foreign):
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    assert pidfile.live_postmaster(paths) is None


def test_a_pid_file_of_another_data_directory_is_not_ours(pg, foreign, tmp_path):
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port, data_dir=tmp_path / "elsewhere")
    _record(pg, proc.pid, port)
    assert pidfile.live_postmaster(paths) is None


def test_permission_error_is_not_ours_even_with_a_listener(pg, foreign, monkeypatch):
    # M3 (round-3 N3): every other fact says "ours"; only EPERM differs.
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    _record(pg, proc.pid, port)
    assert pidfile.live_postmaster(paths) is not None  # the control
    from mcp_server.infrastructure import managed_pg_process

    def eperm(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(managed_pg_process.os, "kill", eperm)
    assert pidfile.live_postmaster(paths) is None


def test_a_dead_pid_is_not_ours(pg):
    _managed_pg, server, paths = pg
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    _pid_file(paths, proc.pid, 5432)
    _record(pg, proc.pid, 5432, started="1.000000")
    assert pidfile.live_postmaster(paths) is None


def test_a_zombie_has_no_start_time(pg, request):
    # An exited, unreaped postmaster (no init in a container) must read as
    # gone, or a wait for its exit would never end.
    from mcp_server.infrastructure import managed_pg_process

    _managed_pg, server, paths = pg
    exit_r, exit_w = os.pipe()
    proc = subprocess.Popen([sys.executable, "-c", "pass"], pass_fds=(exit_w,))
    os.close(exit_w)
    try:
        server._until(paths.cluster, exit_r, lambda: managed_pg_process.exited(exit_r))
    finally:
        os.close(exit_r)
    try:
        # Kernel exit notification does not reap the child, including on macOS
        # where os.waitid is absent. Use the suite's configured test deadline.
        deadline = time.monotonic() + float(request.config.getini("timeout"))
        wait_for_process_exit(proc.pid, deadline)
        assert managed_pg_process.alive_as_this_user(proc.pid)  # an entry: a zombie
        assert managed_pg_process.started(proc.pid) is None
    finally:
        proc.wait()


def test_start_never_adopts_or_dials_a_foreign_listener(pg, foreign, tmp_path):
    # B2, start path: foreign.py / stopprobe.py of the round-3 review.
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    _record(pg, proc.pid, port, started="1.000000")
    binaries = fake_postgres.install(tmp_path / "bin").parent
    got, postmaster = server.start(binaries, paths)
    try:
        assert got != port and postmaster is not None
        assert pidfile.read_lockfile(paths.cluster).pid == postmaster.pid
    finally:
        server.stop(paths, postmaster)
    assert proc.poll() is None  # the foreign process was not signalled
    assert _dialled(proc) == []  # nor dialled


def test_stop_never_signals_a_foreign_process(pg, foreign):
    # B2, stop path: the old stop() ran `pg_ctl -D <cluster> -m fast -w stop`.
    _managed_pg, server, paths = pg
    proc, port = foreign()
    _pid_file(paths, proc.pid, port)
    _record(pg, proc.pid, port, started="1.000000")
    server.stop(paths, None)
    assert proc.poll() is None
    assert (paths.cluster / "postmaster.pid").exists()  # stop never removes it
    assert _dialled(proc) == []


def test_start_waits_for_ready_then_proves_with_the_password(pg, tmp_path):
    _managed_pg, server, paths = pg
    binaries = fake_postgres.install(tmp_path / "bin").parent
    port, postmaster = server.start(binaries, paths)
    try:
        lock = pidfile.read_lockfile(paths.cluster)
        assert (lock.pid, lock.port, lock.status) == (postmaster.pid, port, "ready")
        assert (paths.root / "connections.log").read_text() == "connection\n"
    finally:
        server.stop(paths, postmaster)
    assert postmaster.returncode == 0
    assert not (paths.cluster / "postmaster.pid").exists()


def test_a_server_without_the_cluster_password_fails_and_is_stopped(
    pg, tmp_path, monkeypatch
):
    _managed_pg, server, paths = pg
    from mcp_server.infrastructure import managed_pg_protocol

    def wrong_password(_paths, port):
        managed_pg_protocol.authenticate(HOST, port, "postgres", "not-ours")

    monkeypatch.setattr(server, "_prove", wrong_password)
    binaries = fake_postgres.install(tmp_path / "bin").parent
    with pytest.raises(managed_pg_protocol.ProtocolError, match="28P01"):
        server.start(binaries, paths)
    assert pidfile.live_postmaster(paths) is None
    assert not (paths.cluster / "postmaster.pid").exists()


def test_a_postmaster_that_exits_fails_with_its_log(pg, tmp_path, monkeypatch):
    _managed_pg, server, paths = pg
    monkeypatch.setenv("FAKE_PG_FAIL", "FATAL:  could not create shared memory")
    binaries = fake_postgres.install(tmp_path / "bin").parent
    with pytest.raises(server.ServerError, match="could not create shared memory"):
        server.start(binaries, paths)


def test_the_exit_is_read_from_the_pipe_not_from_waitpid(pg, tmp_path, monkeypatch):
    # Descriptors close before a process becomes reapable: after the last
    # event poll() may still say "running". Only the end of file decides.
    _managed_pg, server, paths = pg
    monkeypatch.setenv("FAKE_PG_FAIL", "FATAL:  lock file exists")

    # poll() raises: code that decides the exit by waitpid fails at its first
    # call, an assertion, not a hang (round-4 review B4). Popen.wait() never
    # calls poll(), so the product's reaping is unaffected.
    def poll_decides(self):
        raise AssertionError("poll() decided the exit")

    monkeypatch.setattr(subprocess.Popen, "poll", poll_decides)
    binaries = fake_postgres.install(tmp_path / "bin").parent
    with pytest.raises(server.ServerError, match="lock file exists"):
        server.start(binaries, paths)
