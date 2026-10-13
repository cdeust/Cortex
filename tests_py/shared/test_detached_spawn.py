"""Popen options of a detached spawn, per platform and per job state (issue #684).

The decision runs everywhere; the Windows CI leg also measures the real job of
its runner and starts a real child with the decided flags.

source: ADR-1102"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_server.infrastructure import embedding_downloads
from mcp_server.shared import detached_spawn as d
from mcp_server.shared import win32_job as j
from tests_py._windows_spawn_fake import (
    as_windows_in_breakaway_job,
    assert_detached_on_windows,
)

# source: ADR-1102 — the base flags, CREATE_NEW_PROCESS_GROUP and CREATE_NO_WINDOW
BASE = 0x00000200 | 0x08000000
# source: ADR-1102 — the breakaway request, CREATE_BREAKAWAY_FROM_JOB
BREAKAWAY = 0x01000000
_QUEUE = (
    Path(__file__).resolve().parents[2]
    / "plugins/hypermnesia-mcp-codex/scripts/session_queue.py"
)


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        (None, BASE),
        (0, BASE),
        (j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, BASE),
        (j.JOB_OBJECT_LIMIT_BREAKAWAY_OK, BASE | BREAKAWAY),
        (
            j.JOB_OBJECT_LIMIT_BREAKAWAY_OK | j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            BASE | BREAKAWAY,
        ),
        (j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK, BASE),
        (
            j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK | j.JOB_OBJECT_LIMIT_BREAKAWAY_OK,
            BASE,
        ),
    ],
)
def test_breakaway_is_requested_only_where_the_job_accepts_the_request(
    limits, expected
):
    assert d.windows_creationflags(limits) == expected


def test_no_window_never_meets_detached_process():
    # CREATE_NO_WINDOW is ignored next to DETACHED_PROCESS (Microsoft page)
    assert not d.windows_creationflags(None) & 0x00000008


def test_windows_passes_creationflags_only():
    assert d.platform_options("win32", None) == {"creationflags": BASE}


@pytest.mark.parametrize("platform", ["linux", "darwin", "freebsd14"])
def test_posix_passes_a_new_session_only(platform):
    assert d.platform_options(platform, None) == {"start_new_session": True}


def test_posix_options_never_probe_a_job(monkeypatch):
    monkeypatch.setattr(d, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(j, "job_limit_flags", pytest.fail)
    assert d.options() == {"start_new_session": True}


def test_windows_options_come_from_the_measured_job(monkeypatch):
    as_windows_in_breakaway_job(monkeypatch)
    assert_detached_on_windows(d.options())


def test_an_unreadable_job_fails_the_spawn_instead_of_guessing(monkeypatch):
    def unreadable():
        raise OSError(5, "QueryInformationJobObject failed")

    monkeypatch.setattr(d, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(j, "job_limit_flags", unreadable)
    with pytest.raises(OSError, match="QueryInformationJobObject"):
        d.options()


@pytest.mark.parametrize(
    ("limits", "warned"),
    [
        (j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, True),
        (0, False),
        (None, False),
        (j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | j.JOB_OBJECT_LIMIT_BREAKAWAY_OK, False),
        (
            j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
            False,
        ),
    ],
)
def test_a_child_bound_to_a_killing_job_is_reported(
    monkeypatch, caplog, limits, warned
):
    monkeypatch.setattr(d, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(j, "job_limit_flags", lambda: limits)
    with caplog.at_level(logging.WARNING, logger=d.__name__):
        d.options()
    assert ("ends when the job closes" in caplog.text) is warned


def test_embedding_downloads_detach_through_the_shared_options(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        embedding_downloads.subprocess, "Popen", lambda cmd, **kw: seen.update(kw)
    )
    as_windows_in_breakaway_job(monkeypatch)
    embedding_downloads._spawn_detached(["true"], "fixture")
    assert_detached_on_windows(seen)


def test_the_codex_queue_repeats_the_shared_base_flags():
    spec = importlib.util.spec_from_file_location("codex_session_queue", _QUEUE)
    queue = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue)
    assert queue.WINDOWS_DETACH_FLAGS == d.windows_creationflags(None)


@pytest.mark.skipif(sys.platform != "win32", reason="real kernel32 and CreateProcess")
def test_a_real_child_starts_with_the_flags_decided_for_this_job():
    limits = j.job_limit_flags()
    options = d.options()
    assert options == {"creationflags": d.windows_creationflags(limits)}
    child = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )
    assert child.wait(timeout=60) == 0
