"""Win32 security plumbing for the broker's named pipe (ADR-1112 owner
decision 2): the current user's SID, an owner-only DACL, and the ctypes and
``_winapi`` access every caller narrows to Windows.

Split from ``broker_pipe`` under the 300-line cap.

source: Microsoft Docs: CreateNamedPipeW, OpenProcessToken,
GetTokenInformation, ConvertSidToStringSidW,
ConvertStringSecurityDescriptorToSecurityDescriptorW
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

PIPE_ACCESS_DUPLEX = 0x00000003  # source: winbase.h (CreateNamedPipeW dwOpenMode)
FILE_FLAG_OVERLAPPED = 0x40000000  # source: winbase.h (CreateNamedPipeW, CreateFileW)
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000  # source: winbase.h (CreateNamedPipeW)
PIPE_TYPE_MESSAGE = 0x00000004  # source: winbase.h (CreateNamedPipeW dwPipeMode)
PIPE_READMODE_MESSAGE = 0x00000002  # source: winbase.h (CreateNamedPipeW dwPipeMode)
PIPE_REJECT_REMOTE_CLIENTS = (
    0x00000008  # source: winbase.h (CreateNamedPipeW dwPipeMode)
)
PIPE_UNLIMITED_INSTANCES = 255  # source: winbase.h (CreateNamedPipeW nMaxInstances)
GENERIC_READ_WRITE = (
    0x80000000 | 0x40000000
)  # source: winnt.h GENERIC_READ | GENERIC_WRITE
OPEN_EXISTING = 3  # source: fileapi.h (CreateFileW dwCreationDisposition)
ERROR_FILE_NOT_FOUND = 2  # source: winerror.h
ERROR_PIPE_BUSY = 231  # source: winerror.h
TOKEN_QUERY = 0x0008  # source: winnt.h (OpenProcessToken DesiredAccess)
TOKEN_USER_CLASS = 1  # source: winnt.h TOKEN_INFORMATION_CLASS.TokenUser
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # source: winnt.h (OpenProcess)
SDDL_REVISION_1 = (
    1  # source: sddl.h (ConvertStringSecurityDescriptorToSecurityDescriptorW)
)
# source: ADR-1112 pipe buffers sized like the Unix socket defaults (64 KiB)
_BUFFER = 64 * 1024


class SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


def supported() -> bool:
    return sys.platform == "win32"


def _api() -> tuple[Any, Any]:
    if sys.platform != "win32":
        raise OSError("named pipes are Windows-only")
    return ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL(
        "advapi32", use_last_error=True
    )


def _last_error() -> int:
    if sys.platform != "win32":
        raise OSError("named pipes are Windows-only")
    return ctypes.get_last_error()


def _win_error(code: int | None = None) -> OSError:
    if sys.platform != "win32":
        raise OSError("named pipes are Windows-only")
    return ctypes.WinError(ctypes.get_last_error() if code is None else code)


def _winapi() -> Any:
    """CPython's private Windows API module, as ``multiprocessing`` uses it."""
    if sys.platform != "win32":
        raise OSError("named pipes are Windows-only")
    import _winapi  # noqa: PLC0415 — Windows only

    return _winapi


def _token_sid(process_handle: int) -> str:
    kernel32, advapi32 = _api()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        raise _win_error()
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size)
        )
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TOKEN_USER_CLASS, buffer, size, ctypes.byref(size)
        ):
            raise _win_error()
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0]
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise _win_error()
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def current_user_sid() -> str:
    kernel32, _ = _api()
    return _token_sid(kernel32.GetCurrentProcess())


def owner_only_sddl(sid: str) -> str:
    """A protected DACL (no inherited ACE) with one ACE: generic access for
    ``sid``. Every other principal, Administrators and SYSTEM included, is
    denied by omission."""
    if not sid.startswith("S-1-") or any(c in sid for c in "();:"):
        raise ValueError(f"not a SID string: {sid!r}")
    return f"D:P(A;;GA;;;{sid})"


def owner_only_attributes() -> tuple[SecurityAttributes, Any]:
    """SECURITY_ATTRIBUTES whose DACL grants access to this SID only."""
    _, advapi32 = _api()
    descriptor = wintypes.LPVOID()
    sddl = owner_only_sddl(current_user_sid())
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None
    ):
        raise _win_error()
    attributes = SecurityAttributes(
        ctypes.sizeof(SecurityAttributes), descriptor, False
    )
    return attributes, descriptor
