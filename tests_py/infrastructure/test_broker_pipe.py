"""The broker's Windows named-pipe transport (ADR-1112 owner decision 2).

The pure parts (SDDL, pipe name) run everywhere. The rest runs only on
Windows, in CI's ``test-windows`` job: the DACL read back from a live pipe
has one ACE and it is the current user's SID, a second broker cannot take
over an existing pipe name, the client verifies the serving process's SID,
and a request round-trips through a real ``BrokerServer`` on the pipe.

source: ADR-1112
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

broker_pipe = pytest.importorskip("mcp_server.infrastructure.broker_pipe")
broker_win32 = pytest.importorskip("mcp_server.infrastructure.broker_win32")

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes")


def test_the_dacl_grants_one_sid_and_inherits_nothing():
    sid = "S-1-5-21-1004336348-1177238915-682003330-1001"
    assert broker_win32.owner_only_sddl(sid) == f"D:P(A;;GA;;;{sid})"


@pytest.mark.parametrize("bad", ["", "Everyone", "S-1-1-0)(A;;GA;;;WD", "WD"])
def test_anything_but_a_sid_string_is_refused(bad):
    with pytest.raises(ValueError):
        broker_win32.owner_only_sddl(bad)


def test_the_pipe_name_is_per_user_and_per_store(monkeypatch):
    monkeypatch.setattr(broker_pipe, "current_user_sid", lambda: "S-1-5-21-1")
    first = broker_pipe.pipe_name("store-a")
    assert first.startswith("\\\\.\\pipe\\cortex-store-broker-")
    assert first != broker_pipe.pipe_name("store-b")
    monkeypatch.setattr(broker_pipe, "current_user_sid", lambda: "S-1-5-21-2")
    assert first != broker_pipe.pipe_name("store-a")


def _unique_name() -> str:
    return broker_pipe.pipe_name(f"test-{os.getpid()}-{time.monotonic_ns()}")


def _dacl_of(handle: int) -> str:
    import ctypes  # noqa: PLC0415 — Windows only
    from ctypes import wintypes  # noqa: PLC0415 — Windows only

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = wintypes.LPVOID()
    se_kernel_object, dacl_information = 6, 4  # winnt.h / accctrl.h
    status = advapi32.GetSecurityInfo(
        wintypes.HANDLE(handle),
        se_kernel_object,
        dacl_information,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    assert status == 0, status
    text = wintypes.LPWSTR()
    assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        descriptor, 1, dacl_information, ctypes.byref(text), None
    )
    try:
        return text.value or ""
    finally:
        kernel32.LocalFree(text)
        kernel32.LocalFree(descriptor)


@windows
def test_a_live_pipe_carries_only_the_current_users_ace():
    listener = broker_pipe.PipeListener(_unique_name())
    try:
        dacl = _dacl_of(listener._pending)  # noqa: SLF001 — inspecting the live instance
        assert dacl.startswith("D:P"), dacl
        assert dacl.count("(A;") == 1, dacl
        assert broker_pipe.current_user_sid() in dacl, dacl
    finally:
        listener.close()


@windows
def test_a_second_broker_cannot_take_an_existing_pipe_name():
    name = _unique_name()
    listener = broker_pipe.PipeListener(name)
    try:
        with pytest.raises(OSError):
            broker_pipe.PipeListener(name)
    finally:
        listener.close()


@windows
def test_a_request_round_trips_over_the_pipe():
    from mcp_server.infrastructure.broker_client import BrokerClient, BrokerStore  # noqa: PLC0415
    from mcp_server.infrastructure.broker_executor import StoreExecutor  # noqa: PLC0415
    from mcp_server.infrastructure.broker_scheduler import SchedulerPolicy  # noqa: PLC0415
    from mcp_server.infrastructure.broker_server import (  # noqa: PLC0415
        BrokerServer,
        Identity,
        ServerPolicy,
    )
    from mcp_server.infrastructure.schema_versions import SCHEMA_VERSION  # noqa: PLC0415

    class _Store:
        def get_memory(self, memory_id: int) -> dict:
            return {"id": memory_id}

    name = _unique_name()
    listener = broker_pipe.PipeListener(name)
    executor = StoreExecutor(_Store())
    server = BrokerServer(
        listener.accept,
        executor,
        ServerPolicy(SchedulerPolicy(1, 1, 4), idle_seconds=60.0, max_connections=4),
        Identity("test", SCHEMA_VERSION),
    )
    thread = threading.Thread(target=server.run, args=(listener.close,), daemon=True)
    thread.start()
    try:
        client = BrokerClient(
            lambda deadline: broker_pipe.connect_or_spawn(name, deadline, lambda: None),
            "test",
        )
        store = BrokerStore(client, executor.methods)
        assert store.get_memory(5) == {"id": 5}
        assert store.broker_pid() == os.getpid()
        store.close()
    finally:
        server.stop()
        thread.join(timeout=10)
