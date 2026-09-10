"""Kernel peer identity for Unix capture sockets; no application credentials.

Sources: Linux unix(7) SO_PEERCRED; Apple getpeereid(3). Both sides check UID,
in addition to the private directory and socket's filesystem permissions.
"""

from __future__ import annotations

import ctypes
import os
import socket
import struct
import sys


def supported() -> None:
    if sys.platform not in {"linux", "darwin"} or not hasattr(socket, "AF_UNIX"):
        raise OSError(
            "capture worker requires Linux/macOS Unix sockets; no TCP fallback"
        )


def peer_uid(connection: socket.socket) -> int:
    supported()
    if sys.platform == "linux":
        # source: ADR-0510
        credentials = struct.Struct("iII")
        value = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, credentials.size
        )
        return credentials.unpack(value)[1]
    # source: ADR-0510
    library = ctypes.CDLL(None, use_errno=True)
    getpeereid = library.getpeereid
    getpeereid.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    getpeereid.restype = ctypes.c_int
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if getpeereid(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)):
        raise OSError(ctypes.get_errno(), "cannot authenticate capture socket peer")
    return uid.value


def authenticate(connection: socket.socket) -> None:
    if peer_uid(connection) != os.geteuid():
        raise PermissionError("capture socket peer belongs to a different user")
