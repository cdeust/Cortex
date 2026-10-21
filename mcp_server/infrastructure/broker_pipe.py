"""The broker's Windows transport: a named pipe only the user's SID can open.

CPython on Windows has no ``AF_UNIX`` (ADR-1094). The standard local IPC is
a named pipe; its DACL does what the socket file mode does on Unix. The
broker creates every pipe instance with a protected DACL granting generic
access to the current user's SID and nobody else (SDDL ``D:P(A;;GA;;;<SID>)``),
the first instance with ``FILE_FLAG_FIRST_PIPE_INSTANCE`` so that a pipe of
that name created earlier by anyone makes the broker fail instead of
sharing it, and remote clients rejected (``PIPE_REJECT_REMOTE_CLIENTS``).
A client checks, before sending anything, that the process serving the pipe
runs as its own SID (``GetNamedPipeServerProcessId``, process token). Message
framing is ``multiprocessing.connection.PipeConnection``'s; the same size
limits apply. The pipe name is the single-instance lease: only one process
can own the first instance.

source: ADR-1112 owner decision 2; Microsoft Docs: CreateNamedPipeW,
ConvertStringSecurityDescriptorToSecurityDescriptorW, GetNamedPipeServerProcessId,
"Named Pipe Security and Access Rights"
"""

from __future__ import annotations

import ctypes
import hashlib
import time
from ctypes import wintypes
from collections.abc import Callable

from mcp_server.infrastructure.broker_protocol import ProtocolError, remaining
from mcp_server.infrastructure.broker_win32 import (
    _BUFFER,
    ERROR_FILE_NOT_FOUND,
    ERROR_PIPE_BUSY,
    FILE_FLAG_FIRST_PIPE_INSTANCE,
    FILE_FLAG_OVERLAPPED,
    GENERIC_READ_WRITE,
    OPEN_EXISTING,
    PIPE_ACCESS_DUPLEX,
    PIPE_READMODE_MESSAGE,
    PIPE_REJECT_REMOTE_CLIENTS,
    PIPE_TYPE_MESSAGE,
    PIPE_UNLIMITED_INSTANCES,
    PROCESS_QUERY_LIMITED_INFORMATION,
    _api,
    _last_error,
    _token_sid,
    _win_error,
    _winapi,
    current_user_sid,
    owner_only_attributes,
)


def pipe_name(store_key: str) -> str:
    """``\\\\.\\pipe\\cortex-store-broker-<16 hex>``: one per user and store."""
    digest = hashlib.sha256(f"{current_user_sid()}|{store_key}".encode()).hexdigest()
    return rf"\\.\pipe\cortex-store-broker-{digest[:16]}"


def create_instance(name: str, first: bool) -> int:
    """One pipe instance with the owner-only DACL; raises if squatted."""
    kernel32, _ = _api()
    attributes, descriptor = owner_only_attributes()
    try:
        flags = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED
        if first:
            flags |= FILE_FLAG_FIRST_PIPE_INSTANCE
        kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
        handle = kernel32.CreateNamedPipeW(
            name,
            flags,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES,
            _BUFFER,
            _BUFFER,
            0,
            ctypes.byref(attributes),
        )
        if handle in (None, wintypes.HANDLE(-1).value):
            raise _win_error()
        return int(handle)
    finally:
        kernel32.LocalFree(descriptor)


def _server_is_this_user(handle: int) -> bool:
    kernel32, _ = _api()
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
        raise _win_error()
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        raise _win_error()
    try:
        return _token_sid(process) == current_user_sid()
    finally:
        kernel32.CloseHandle(process)


def open_client(name: str, deadline: float) -> int:
    """Open the pipe, waiting for a free instance; verify the server's SID."""
    kernel32, _ = _api()
    kernel32.CreateFileW.restype = wintypes.HANDLE
    while True:
        handle = kernel32.CreateFileW(
            name, GENERIC_READ_WRITE, 0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None
        )
        if handle not in (None, wintypes.HANDLE(-1).value):
            break
        error = _last_error()
        if error == ERROR_FILE_NOT_FOUND:
            raise FileNotFoundError(name)
        if error != ERROR_PIPE_BUSY:
            raise _win_error(error)
        left = remaining(deadline) or 0.0
        kernel32.WaitNamedPipeW(name, int(min(left, 1.0) * 1000))
    if not _server_is_this_user(int(handle)):
        kernel32.CloseHandle(handle)
        raise PermissionError("the store broker pipe is served by another user")
    winapi = _winapi()
    # message read mode, as multiprocessing.connection.PipeClient sets it
    winapi.SetNamedPipeHandleState(
        int(handle), winapi.PIPE_READMODE_MESSAGE, None, None
    )
    return int(handle)


class PipeChannel:
    """Framed messages over one connected pipe handle (message mode)."""

    def __init__(self, handle: int) -> None:
        from multiprocessing.connection import PipeConnection  # type: ignore[attr-defined]  # noqa: PLC0415 — Windows only

        self.conn = PipeConnection(handle)

    def send_frame(self, data: bytes, limit: int, deadline: float | None) -> None:
        if len(data) > limit:
            raise ProtocolError(f"frame of {len(data)} bytes exceeds {limit}")
        self.conn.send_bytes(data)

    def recv_frame(self, limit: int, deadline: float | None) -> bytes:
        left = remaining(deadline)
        if left is not None and not self.conn.poll(left):
            raise TimeoutError("broker deadline exceeded")
        try:
            return self.conn.recv_bytes(limit)
        except OSError as exc:
            raise ConnectionError(str(exc)) from exc

    def close(self) -> None:
        try:
            self.conn.close()
        except OSError:
            pass


def wait_for_pipe(name: str, deadline: float) -> int:
    """Open the pipe as soon as a freshly spawned broker creates it."""
    while True:
        try:
            return open_client(name, deadline)
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                raise
            # source: ADR-1112 re-probe interval; the caller's deadline bounds it
            time.sleep(0.05)


class PipeListener:
    """Accepts clients on owner-only pipe instances, one instance per client
    (``multiprocessing.connection.PipeListener.accept``'s overlapped connect).
    The first instance is created with FILE_FLAG_FIRST_PIPE_INSTANCE: a pipe
    of this name created by anyone before makes the broker fail to start."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._pending = create_instance(name, first=True)
        self._closed = False

    def accept(self) -> PipeChannel:
        winapi = _winapi()

        handle = self._pending
        self._pending = create_instance(self.name, first=False)
        try:
            overlapped = winapi.ConnectNamedPipe(handle, overlapped=True)
        except OSError as exc:
            if getattr(exc, "winerror", None) != winapi.ERROR_NO_DATA:
                raise
        else:
            try:
                winapi.WaitForMultipleObjects(
                    [overlapped.event], False, winapi.INFINITE
                )
            except BaseException:
                overlapped.cancel()
                winapi.CloseHandle(handle)
                raise
            finally:
                _, err = overlapped.GetOverlappedResult(True)
                if err not in (0, winapi.ERROR_PIPE_CONNECTED):
                    winapi.CloseHandle(handle)
                    raise OSError(err, "ConnectNamedPipe failed")
        return PipeChannel(handle)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _winapi().CloseHandle(self._pending)


def connect_or_spawn(
    name: str, deadline: float, spawn: Callable[[], None]
) -> PipeChannel:
    """Connect to the broker's pipe, launching the broker once if absent.

    No lock file: the pipe name is the lease. The broker creates its first
    instance with FILE_FLAG_FIRST_PIPE_INSTANCE, so when two clients launch
    at once the second broker cannot create the pipe and exits, and both
    clients connect to the first."""
    try:
        return PipeChannel(open_client(name, deadline))
    except FileNotFoundError:
        spawn()
    return PipeChannel(wait_for_pipe(name, deadline))
