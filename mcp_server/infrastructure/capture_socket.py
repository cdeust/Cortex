"""Private socket paths and kernel lifetime leases for resident capture.

source: ADR-0512"""

from __future__ import annotations

import os
import socket
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mcp_server.infrastructure.capture_peer import authenticate, supported
from mcp_server.infrastructure.capture_lock import wait_for_lock

if sys.platform != "win32":
    import fcntl

# source: ADR-0512
PRIVATE_FILE = 0o600
# source: ADR-0512
PRIVATE_DIR = 0o700


def _check_directory(path: Path, private: bool = False) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise PermissionError(f"capture path is not a real directory: {path}")
    if info.st_uid not in {0, os.geteuid()}:
        raise PermissionError(f"capture directory has an untrusted owner: {path}")
    writable = info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
    if writable and not sticky_root:
        raise PermissionError(f"capture directory is writable by other users: {path}")
    if private and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != PRIVATE_DIR
    ):
        raise PermissionError(f"capture runtime directory must be owner-only: {path}")


def runtime_directory(root: Path) -> Path:
    supported()
    root = root.expanduser().absolute()
    for parent in reversed(root.parents):
        _check_directory(parent)
    root.mkdir(mode=PRIVATE_DIR, exist_ok=True)
    _check_directory(root)
    if root.lstat().st_uid != os.geteuid():
        raise PermissionError("capture root must belong to the current user")
    runtime = root / ".capture-worker"
    runtime.mkdir(mode=PRIVATE_DIR, exist_ok=True)
    _check_directory(runtime, private=True)
    return runtime


def _check_file(info: os.stat_result, socket_file: bool) -> None:
    expected_type = stat.S_ISSOCK if socket_file else stat.S_ISREG
    if not expected_type(info.st_mode) or info.st_uid != os.geteuid():
        raise PermissionError("capture endpoint has invalid type or owner")
    if stat.S_IMODE(info.st_mode) != PRIVATE_FILE:
        raise PermissionError("capture endpoint must have mode 0600")


@contextmanager
def lease(path: Path, deadline: float | None = None) -> Iterator[int]:
    supported()
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, PRIVATE_FILE)
    try:
        _check_file(os.fstat(descriptor), socket_file=False)
        if deadline is None:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            wait_for_lock(descriptor, deadline)
        yield descriptor
    finally:
        # source: ADR-0512
        os.close(descriptor)


def connect(path: Path, timeout: float) -> socket.socket:
    _check_file(path.lstat(), socket_file=True)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect(str(path))
        authenticate(connection)
        return connection
    except BaseException:
        connection.close()
        raise


def remove_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    _check_file(info, socket_file=True)
    path.unlink()


def listen(path: Path) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.bind(str(path))
        path.chmod(PRIVATE_FILE)
        connection.listen()  # source: ADR-0512
        return connection
    except BaseException:
        connection.close()
        raise
