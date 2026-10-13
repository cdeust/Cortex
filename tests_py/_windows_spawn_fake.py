"""Run a spawn site as if on Windows, inside a job that allows breakaway.

On macOS and Linux ``start_new_session`` is what every detached spawn passes, so
a site that bypasses ``detached_spawn`` would still pass a POSIX assertion. Under
this fake the only way to produce the expected ``creationflags`` is to go
through ``detached_spawn.options()``.

source: ADR-1102"""

from __future__ import annotations

from types import SimpleNamespace

from mcp_server.shared import detached_spawn, win32_job

# CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB
# source: ADR-1102 (a job with JOB_OBJECT_LIMIT_BREAKAWAY_OK)
EXPECTED_CREATIONFLAGS = 0x00000200 | 0x08000000 | 0x01000000


def as_windows_in_breakaway_job(monkeypatch) -> None:
    monkeypatch.setattr(detached_spawn, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        win32_job,
        "job_limit_flags",
        lambda: win32_job.JOB_OBJECT_LIMIT_BREAKAWAY_OK,
    )


def assert_detached_on_windows(kwargs: dict) -> None:
    assert kwargs["creationflags"] == EXPECTED_CREATIONFLAGS
    assert "start_new_session" not in kwargs
