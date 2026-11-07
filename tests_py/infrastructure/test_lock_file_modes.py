"""Every lock file Cortex opens is owner-only (review of PR #775, N6).

The pipeline install lock and the groomer decision lock were created 0644;
the others were created 0600 but a lock left 0644 by an older version kept
that mode. Each lock below is taken once on a fresh path and once on a path
holding a 0644 file, with umask 022.
"""

from __future__ import annotations

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")


@contextmanager
def _pipeline_install(lock: Path):
    from mcp_server.infrastructure import pipeline_install_lock as module

    saved = module._LOCK_FILE
    module._LOCK_FILE = lock
    try:
        with module.install_lock():
            yield
    finally:
        module._LOCK_FILE = saved


@contextmanager
def _groomer(lock: Path):
    from mcp_server.infrastructure.groomer_coordinator_io import DecisionLock

    with DecisionLock(lock) as held:
        assert held
        yield


@contextmanager
def _log_writer(lock: Path):
    from mcp_server.shared.log_file_lock import log_file_lock

    with log_file_lock(lock.with_suffix("")):
        yield


@contextmanager
def _drain(lock: Path):
    from mcp_server.infrastructure.capture_spool import drain_lock

    with drain_lock(lock.parent / "spool.jsonl") as held:
        assert held
        yield


@contextmanager
def _counter(lock: Path):
    from mcp_server.infrastructure.hook_counter_lock import counter_lock

    with counter_lock(lock):
        yield


_LOCKS = {
    "pipeline-install": (_pipeline_install, ".install.lock"),
    "groomer-decision": (_groomer, "decision.lock"),
    "log-writer": (_log_writer, "x.log.lock"),
    "capture-drain": (_drain, "drain.lock"),
    "hook-counter": (_counter, "counter.lock"),
}


@pytest.fixture
def umask_022():
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "left-0644"])
@pytest.mark.parametrize("name", sorted(_LOCKS))
def test_lock_file_is_owner_only(umask_022, tmp_path, name, existing):
    take, filename = _LOCKS[name]
    lock = tmp_path / filename
    if existing:
        lock.write_text("")
        lock.chmod(0o644)
    with take(lock):
        assert stat.S_IMODE(lock.stat().st_mode) == 0o600
