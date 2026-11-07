"""``postmaster.pid`` of one managed cluster: what it says, and whom it proves.

Two proofs, both from the kernel, neither dials anything:

- ``live_postmaster``: the postmaster Cortex spawned and recorded in
  ``postmaster.json`` (``{pid, started, port}``) is alive with the same kernel
  start time.
- ``written_by``: the process the file names started no later than the file
  says (line 3, ``MyStartTime``) plus ``_START_SLACK``, so it is the file's
  writer, a postmaster of this cluster, whoever started it. A process that
  started later is a reused PID and the file is stale.

source: ADR-1114
source: PostgreSQL src/include/utils/pidfile.h (postmaster.pid lines)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp_server.infrastructure import managed_pg as _pg
from mcp_server.infrastructure import managed_pg_process as _process

# source: pidfile.h LOCK_FILE_LINE_PID 1, _DATA_DIR 2, _PORT 4, _PM_STATUS 8
# source: pidfile.h LOCK_FILE_LINE_START_TIME 3 (``MyStartTime``, time(NULL))
_PID, _DATA_DIR, _START, _PORT, _STATUS = 0, 1, 2, 3, 7
# A process whose kernel start time is later than the file's start time plus
# this slack started after the file was written: a reused PID, not its writer.
# 1 s: line 3 is whole seconds taken after exec; 1 s more: Linux ``btime`` is
# whole seconds. Measured kernel start minus a whole-second clock read taken
# by the process itself, 20 runs each: macOS arm64 max 0.911 s (real PG 18.6:
# 1792268628 in the file, 1792268628.936399 from the kernel), Linux arm64 max
# -0.190 s, Linux x86_64 under qemu max -2.520 s. source: ADR-1114 (round 6)
_START_SLACK = 2.0
READY = "ready"  # source: pidfile.h PM_STATUS_READY ("ready   ")


@dataclass(frozen=True)
class LockFile:
    """The lines of ``postmaster.pid`` this module reads."""

    pid: int
    data_dir: str
    port: int
    status: str
    start: int = 0  # line 3: when the writing postmaster started (epoch s)


def read_lockfile(cluster: Path) -> LockFile | None:
    """``postmaster.pid`` as written, ``None`` when absent or not yet whole."""
    try:
        lines = (cluster / "postmaster.pid").read_text(encoding="utf-8").splitlines()
        status = lines[_STATUS].strip() if len(lines) > _STATUS else ""
        start = int(lines[_START])
        return LockFile(
            int(lines[_PID]), lines[_DATA_DIR], int(lines[_PORT]), status, start
        )
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


def written_by(lock: LockFile) -> bool:
    """Whether ``lock.pid`` is alive as this user and is the file's writer:
    it started no later than line 3 plus ``_START_SLACK``. ``False`` proves the
    file stale (a dead PID, a zombie, or a PID reused after the file)."""
    if not _process.alive_as_this_user(lock.pid):
        return False
    start = _process.start_epoch(lock.pid)
    return start is not None and start <= lock.start + _START_SLACK


def ready(cluster: Path) -> LockFile | None:
    """``postmaster.pid`` when it names this cluster, ``ready``, written by a
    live process of this user (a stale file does not count)."""
    lock = read_lockfile(cluster)
    if lock is None or lock.status != READY:
        return None
    if Path(lock.data_dir).resolve() != cluster.resolve():
        return None
    return lock if written_by(lock) else None
