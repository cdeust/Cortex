"""Broker mode (``CORTEX_TEST_BROKER_MODE=1``): stop the session's store
brokers before the process leak guard looks.

A store broker outlives its clients by design (it exits after
``CORTEX_BROKER_IDLE_SECONDS`` with no client, ADR-1112 decision 1), so at
the end of a broker-mode session the brokers this session launched are still
alive. They are the run's own infrastructure, not a leak: this fixture closes
the shared stores, terminates every broker carrying this session's token and
waits for each to exit, then the leak guard takes its snapshot. Any other
process left alive is still reported.

source: ADR-1112 increment 5
"""

from __future__ import annotations

import os
import signal
import time

import pytest

from tests_py._process_leak_guard import TOKEN_VAR, live_tokened_processes
from tests_py._store_mode import select_store_mode

# Read at store creation, never at import: setting it when conftest imports
# the session fixtures is early enough, and subprocesses inherit it.
select_store_mode()

# source: ADR-1112 the broker's module name, as the launcher runs it
_BROKER_MODULE = "mcp_server.hooks.store_broker"
# source: ADR-1112 harness bound on a terminated broker's exit (pool close)
_EXIT_SECONDS = 10.0


def _brokers() -> list[int]:
    token = os.environ[TOKEN_VAR]
    return [
        pid
        for pid, command in live_tokened_processes(token)
        if _BROKER_MODULE in command
    ]


@pytest.fixture(autouse=True)
def _in_process_store_when_marked(request):
    """A test marked ``in_process_store`` tests the store the broker runs
    (its connections, its class), so in broker mode it gets that store.

    No ``monkeypatch`` here: requesting it from an autouse fixture would
    create every test's monkeypatch earlier and so undo it later, after
    other fixtures' teardown (a patched ``reset_shared_store`` would then
    run at teardown)."""
    marked = request.node.get_closest_marker("in_process_store") is not None
    if os.environ.get("CORTEX_TEST_BROKER_MODE") != "1" or not marked:
        yield
        return
    from mcp_server.infrastructure.memory_store import reset_shared_store  # noqa: PLC0415

    reset_shared_store()
    os.environ["CORTEX_STORE_IN_PROCESS"] = "1"
    try:
        yield
    finally:
        os.environ.pop("CORTEX_STORE_IN_PROCESS", None)
        reset_shared_store()


@pytest.fixture(scope="session", autouse=True)
def _stop_session_brokers(_session_process_leak_guard):
    """Set up after the leak guard, so torn down before it."""
    yield
    if os.environ.get("CORTEX_TEST_BROKER_MODE") != "1":
        return
    from mcp_server.infrastructure.memory_store import reset_shared_store  # noqa: PLC0415

    reset_shared_store()
    pids = _brokers()
    for pid in pids:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + _EXIT_SECONDS
    while _brokers() and time.monotonic() < deadline:
        time.sleep(0.1)  # source: harness poll interval, bounded by _EXIT_SECONDS
