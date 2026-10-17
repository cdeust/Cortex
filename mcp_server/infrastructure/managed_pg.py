"""Attach a process to the plugin's managed PostgreSQL server (ADR-1110).

Stdlib only, POSIX only (``fcntl``). In the wheel, so every surface that reads
the ``managed`` backend marker attaches the same way: the Claude Code launcher,
``python -m mcp_server`` / ``hypermnesia-mcp``, the Codex hook entry
(``mcp_server.hooks.entry``) and the doctor. Claude and Codex on one HOME
therefore share one server and one store.

The cluster root is ``~/.claude/methodology/managed-pg`` (next to the marker,
outside any plugin's data, so uninstalling a plugin never deletes memories);
the binaries stay in the Claude plugin's data, named by ``installed.json``.

Three ``flock`` files under the root order everything, with no timer anywhere:

- ``clients.lock``: every attached process holds it shared until it exits;
  the supervisor's exclusive request is granted when the last one is gone.
- ``start.lock``: held exclusively while the server is started; a client
  waits on it, then reads ``status.json``.
- ``supervisor.lock``: held for the supervisor's whole life, so "is one
  running" is a non-blocking lock attempt.

source: ADR-1110
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping
from urllib.parse import quote

DATABASE = "cortex"  # source: ADR-1110 (the database name every Cortex URL names)
USER = "postgres"  # source: ADR-1110 (the superuser initdb -U creates)
HOST = "127.0.0.1"  # source: ADR-1110 (TCP on loopback only; unix sockets off)
ROOT_ENV = "CORTEX_MANAGED_PG_ROOT"  # source: ADR-1110 (inherited by children)
ROOT_NAME = "managed-pg"  # source: ADR-1110 (the root's name under methodology/)
_SUPERVISOR = "mcp_server.infrastructure.managed_pg_supervisor"  # source: ADR-1110
_HELD: list[int] = []  # client locks, kept open until the process exits
_ATTACHED: dict[str, str] = {}  # root -> URL, valid while the client lock is held


class ManagedPgError(RuntimeError):
    """The managed server could not be made available; the message says why."""


@dataclass(frozen=True)
class PgPaths:
    """Every file of one managed server's cluster root."""

    root: Path

    @property
    def cluster(self) -> Path:
        return self.root / "cluster"

    @property
    def password(self) -> Path:
        return self.root / "password"

    @property
    def status(self) -> Path:
        return self.root / "status.json"

    @property
    def postmaster(self) -> Path:
        """``{pid, started, port}`` of the postmaster the supervisor spawned."""
        return self.root / "postmaster.json"

    @property
    def installed(self) -> Path:
        """The tree and cluster Setup installed (an install fact, not a selection)."""
        return self.root / "installed.json"

    @property
    def provisioned(self) -> Path:
        """Written only after the server started and its schema was set up."""
        return self.root / "provisioned.json"

    @property
    def log(self) -> Path:
        return self.root / "supervisor.log"

    @property
    def server_log(self) -> Path:
        return self.root / "postgres.log"

    def lock(self, name: str) -> Path:
        return self.root / f"{name}.lock"


def root_under(methodology_dir: Path) -> PgPaths:
    """The cluster root next to the backend marker (D5, ADR-1110)."""
    return PgPaths(methodology_dir / ROOT_NAME)


def open_lock(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def flock(fd: int, *, exclusive: bool, blocking: bool = True) -> bool:
    """Take the lock; ``False`` only when non-blocking and already held."""
    import fcntl  # noqa: PLC0415 — POSIX only; never imported on Windows

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, mode if blocking else mode | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def write_json(path: Path, payload: dict) -> None:
    """Replace ``path`` atomically, readable by the owner only."""
    partial = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(partial, path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def database_url(paths: PgPaths, port: int) -> str:
    """The URL of the running server; the password is read from its file."""
    secret = quote(paths.password.read_text(encoding="utf-8").strip(), safe="")
    return f"postgresql://{USER}:{secret}@{HOST}:{port}/{DATABASE}"


def serves(environ: MutableMapping[str, str]) -> PgPaths | None:
    """The managed root ``environ`` already names, when its URL is that server's.

    A process started by one attached to the server (a background worker a
    hook spawns) inherits ``DATABASE_URL`` and ``ROOT_ENV``; it must attach in
    turn, or the server could be stopped under it.
    """
    root = environ.get(ROOT_ENV, "")
    if not root:
        return None
    paths = PgPaths(Path(root))
    status = read_json(paths.status)
    if status.get("state") != "running" or not paths.password.is_file():
        return None
    url = database_url(paths, int(status["port"]))
    return paths if environ.get("DATABASE_URL") == url else None


def _spawn_supervisor(paths: PgPaths, fds: tuple[int, int]) -> None:
    """Start the detached supervisor; it inherits the two locks in ``fds``."""
    package_parent = str(Path(__file__).resolve().parents[2])
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (package_parent, env.get("PYTHONPATH", "")) if p
    )
    argv = [sys.executable, "-m", _SUPERVISOR, str(paths.root), *map(str, fds)]
    log = os.open(paths.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            pass_fds=fds,
            start_new_session=True,
            env=env,
        )
    finally:
        os.close(log)


def _ensure_supervisor(paths: PgPaths) -> None:
    """Spawn the supervisor unless one is alive.

    The start lock comes first: a client that found ``supervisor.lock`` held
    by a peer that had not yet taken the start lock would read a status
    nobody had written (measured on CI, PR #748).
    """
    start = open_lock(paths.lock("start"))
    flock(start, exclusive=True)  # waits out a start in progress
    supervisor = open_lock(paths.lock("supervisor"))
    try:
        if flock(supervisor, exclusive=True, blocking=False):
            _spawn_supervisor(paths, (supervisor, start))
    finally:
        os.close(supervisor)
        os.close(start)


def attach(paths: PgPaths, environ: MutableMapping[str, str]) -> str:
    """Hold this process as a client of the server and return its URL.

    Postcondition: the server is running, or ``ManagedPgError`` carries the
    supervisor's own error. Sets ``ROOT_ENV`` in ``environ`` for children.
    """
    if os.name == "nt":
        raise ManagedPgError("the managed PostgreSQL server does not run on Windows")
    if not paths.root.is_dir():
        raise ManagedPgError(
            f"the managed PostgreSQL root {paths.root} is missing; run "
            "`claude --init-only` to set it up again"
        )
    key = str(paths.root)
    if key not in _ATTACHED:
        _ATTACHED[key] = _attach_once(paths)
    environ[ROOT_ENV] = key
    return _ATTACHED[key]


def _attach_once(paths: PgPaths) -> str:
    clients = open_lock(paths.lock("clients"))
    flock(clients, exclusive=False)
    _HELD.append(clients)
    _ensure_supervisor(paths)
    start = open_lock(paths.lock("start"))
    try:
        flock(start, exclusive=False)  # granted once a start in progress is over
    finally:
        os.close(start)
    status = read_json(paths.status)
    if status.get("state") != "running":
        _HELD.remove(clients)
        os.close(clients)
        raise ManagedPgError(
            "the Cortex PostgreSQL server is not running: "
            f"{status.get('error') or status.get('state') or 'no status written'}"
            f"\nSee {paths.log}"
        )
    return database_url(paths, int(status["port"]))


def use(paths: PgPaths, environ: MutableMapping[str, str]) -> dict[str, str]:
    """Attach and point the engine at the server; the variables set."""
    additions = {
        "DATABASE_URL": attach(paths, environ),
        "CORTEX_MEMORY_STORE_BACKEND": "postgresql",
    }
    environ.update(additions)
    return additions


def detach() -> None:
    """Release this process's client locks (the supervisor may then stop)."""
    _ATTACHED.clear()
    while _HELD:
        os.close(_HELD.pop())
