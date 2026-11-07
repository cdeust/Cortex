"""Unit tests for the per-window session registry (T2-handlers H1).

Covers the acceptance criteria named in the T2-handlers design and in
the H1 task brief: atomic writes (no partial file ever observable),
nominal read, dead-pid degradation + purge, pid-reuse (start-time
divergence) degradation, tombstone degradation, corrupt/unknown-version
degradation without exception, and the bounded ancestor walk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

import mcp_server.infrastructure.session_registry as sr
from mcp_server.shared import platform as host_platform


@pytest.fixture(autouse=True)
def _clear_start_signature_cache():
    """Isolation: the process-lifetime signature cache is module-level
    global state by design (see the correctness proof in
    session_registry.py above ``_start_signature_cache``) — it must
    outlive individual calls within one server process, but each TEST
    is its own scenario and must not observe a stale entry left by an
    earlier test that happened to reuse the same fake pid number."""
    sr._start_signature_cache.clear()
    yield
    sr._start_signature_cache.clear()


def _patch_dir(tmp_path, monkeypatch):
    target = tmp_path / "session-registry"
    monkeypatch.setattr(sr, "registry_dir", lambda: target)
    return target


def _as_window(monkeypatch, claude_pid: int) -> None:
    """Make ``claude_pid`` this server's window, on every platform.

    The reader tests below are about the registry file, not about how the
    window is found. Faking ``os.getppid`` only reaches the POSIX branch of
    ``_window_claude_pid``; on Windows the reader walks the real process
    table instead (ADR-1096), so those tests read no entry (issue #692,
    class 5). How the window is found has its own tests: the POSIX mapping
    below, the Windows walk in ``test_session_registry_windows.py``."""
    monkeypatch.setattr(sr, "_window_claude_pid", lambda: claude_pid)


def _spawn_dummy_process() -> subprocess.Popen:
    """A real, disposable child process this test can kill for a
    known-dead pid — no mocking of os.kill needed for that scenario."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )


# ── atomic write ────────────────────────────────────────────────────────


def test_atomic_write_no_partial_file(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    path = d / "123.json"
    ok = sr._atomic_write(path, {"v": 1, "a": "b" * 10_000})
    assert ok is True
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["v"] == 1
    # no leftover tmp files
    assert list(d.glob("*.tmp.*")) == []


# ── nominal write + read ────────────────────────────────────────────────


def test_write_and_read_nominal(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: "sig-1")
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    _as_window(monkeypatch, 4242)

    ok = sr.write_session("stem-abc", claude_pid=4242)
    assert ok is True
    assert sr.current_window_session() == "stem-abc"


def test_write_resolves_ancestor_when_pid_not_given(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "find_claude_ancestor", lambda: 9001)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: "sig-9001")
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    _as_window(monkeypatch, 9001)

    assert sr.write_session("stem-x") is True
    assert sr.current_window_session() == "stem-x"


def test_write_no_op_when_ancestor_unresolvable(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "find_claude_ancestor", lambda: None)
    assert sr.write_session("stem-y") is False
    assert list(d.glob("*.json")) == []


def test_write_no_op_when_start_signature_unresolvable(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: None)
    assert sr.write_session("stem-z", claude_pid=1) is False
    assert list(d.glob("*.json")) == []


# ── dead pid → None + purge ─────────────────────────────────────────────


def test_dead_pid_reads_as_none_and_gets_purged(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    proc = _spawn_dummy_process()
    pid = proc.pid
    proc.terminate()
    proc.wait(timeout=5)
    # pid is now dead (reaped, so no zombie ambiguity)

    (d).mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stale-stem",
                "claude_pid": pid,
                "claude_start_time": "sig-dead",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )

    _as_window(monkeypatch, pid)
    assert sr.current_window_session() is None

    removed = sr.purge_dead_entries()
    assert removed == 1
    assert not (d / f"{pid}.json").exists()


# ── pid reuse (start-time divergence) → None ────────────────────────────


def test_start_time_divergence_returns_none(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "555.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stem-old-lineage",
                "claude_pid": 555,
                "claude_start_time": "sig-old",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    _as_window(monkeypatch, 555)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    # simulates pid 555 recycled by a new process with a different start
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: "sig-new")

    assert sr.current_window_session() is None


# ── tombstone → None ─────────────────────────────────────────────────────


def test_tombstone_reads_as_none(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: "sig-t")
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    _as_window(monkeypatch, 777)

    assert sr.write_session("stem-live", claude_pid=777) is True
    assert sr.current_window_session() == "stem-live"

    assert sr.tombstone(777) is True
    assert sr.current_window_session() is None


# ── corrupted file / unknown version → None, no exception ──────────────


def test_corrupted_json_returns_none(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "888.json").write_text("{not valid json", encoding="utf-8")
    _as_window(monkeypatch, 888)
    assert sr.current_window_session() is None  # no exception raised


def test_unknown_schema_version_returns_none(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "999.json").write_text(
        json.dumps({"v": 99, "session_id": "x", "claude_pid": 999}),
        encoding="utf-8",
    )
    _as_window(monkeypatch, 999)
    assert sr.current_window_session() is None


def test_missing_file_returns_none(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    _as_window(monkeypatch, 111111)
    assert sr.current_window_session() is None


def test_pid_mismatch_returns_none(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "222.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stem",
                "claude_pid": 333,  # mismatched key vs recorded value
                "claude_start_time": "sig",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    _as_window(monkeypatch, 222)
    assert sr.current_window_session() is None


# ── how the window is found on POSIX ────────────────────────────────────


def test_posix_window_is_the_parent_process(monkeypatch):
    # POSIX: the MCP server is a direct child of the window's claude
    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    assert sr._window_claude_pid() == 4242


# ── bounded ancestor walk ────────────────────────────────────────────────


def test_ancestor_walk_finds_claude(monkeypatch):
    # simulated tree: hook(getppid=200) -> bash(200) -> claude(100)
    chain = {200: (100, "bash"), 100: (1, "claude")}

    def fake_probe(pid):
        return chain.get(pid)

    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: 200)
    monkeypatch.setattr(sr, "_ppid_and_comm", fake_probe)
    assert sr.find_claude_ancestor() == 100


def test_ancestor_walk_no_match_returns_none(monkeypatch):
    chain = {200: (100, "bash"), 100: (50, "systemd"), 50: (1, "init")}

    def fake_probe(pid):
        return chain.get(pid)

    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: 200)
    monkeypatch.setattr(sr, "_ppid_and_comm", fake_probe)
    assert sr.find_claude_ancestor() is None


def test_ancestor_walk_respects_depth_bound(monkeypatch):
    # a chain with 20 hops and NO claude anywhere in it — must stop at
    # max_depth rather than walking forever / raising.
    chain = {i: (i + 1, "wrapper") for i in range(200, 220)}
    chain[220] = (1, "init")

    def fake_probe(pid):
        return chain.get(pid)

    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: 200)
    monkeypatch.setattr(sr, "_ppid_and_comm", fake_probe)
    assert sr.find_claude_ancestor(max_depth=5) is None


def test_ancestor_walk_probe_failure_returns_none(monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: 300)
    monkeypatch.setattr(sr, "_ppid_and_comm", lambda pid: None)
    assert sr.find_claude_ancestor() is None


# ── purge skips non-json / malformed stems, never raises ────────────────


def test_purge_skips_non_numeric_stems(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "not-a-pid.json").write_text("{}", encoding="utf-8")
    (d / "notes.txt").write_text("irrelevant", encoding="utf-8")
    assert sr.purge_dead_entries() == 0
    assert (d / "not-a-pid.json").exists()


def test_purge_empty_dir_returns_zero(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)  # dir does not even exist yet
    assert sr.purge_dead_entries() == 0


# ── start-signature memoization (perf follow-up to T2-H3) ───────────────


def test_cached_start_signature_hits_after_first_call(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "5001.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stem-cache-hit",
                "claude_pid": 5001,
                "claude_start_time": "sig-5001",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    _as_window(monkeypatch, 5001)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)

    calls = []

    def counting_probe(pid):
        calls.append(pid)
        return "sig-5001"

    monkeypatch.setattr(sr, "_process_start_signature", counting_probe)

    assert sr.current_window_session() == "stem-cache-hit"
    assert sr.current_window_session() == "stem-cache-hit"
    assert sr.current_window_session() == "stem-cache-hit"
    # the expensive probe ran exactly once across 3 calls — cache hit
    assert calls == [5001]


def test_cache_keyed_independently_per_pid(monkeypatch):
    calls = []

    def counting_probe(pid):
        calls.append(pid)
        return f"sig-{pid}"

    monkeypatch.setattr(sr, "_process_start_signature", counting_probe)

    assert sr._cached_process_start_signature(111) == "sig-111"
    assert sr._cached_process_start_signature(222) == "sig-222"
    assert sr._cached_process_start_signature(111) == "sig-111"
    assert sr._cached_process_start_signature(222) == "sig-222"
    # each pid probed exactly once — a simulated ppid change (e.g. the
    # window's claude process dying and this server being reparented,
    # see the module-level correctness proof) is a NEW cache key, not
    # an invalidation of the old one; the old key is simply never
    # looked up again.
    assert calls == [111, 222]


def test_transient_probe_failure_is_not_cached(monkeypatch):
    calls = []
    outcomes = [None, "sig-recovered"]

    def flaky_probe(pid):
        calls.append(pid)
        return outcomes.pop(0)

    monkeypatch.setattr(sr, "_process_start_signature", flaky_probe)

    # first call: probe fails transiently (e.g. a race against pid
    # death) — must NOT be memoized as a permanent None
    assert sr._cached_process_start_signature(333) is None
    # second call: probe now succeeds — must be re-attempted, not
    # short-circuited by a cached failure
    assert sr._cached_process_start_signature(333) == "sig-recovered"
    assert calls == [333, 333]


def test_session_id_change_seen_immediately_despite_cached_signature(
    tmp_path, monkeypatch
):
    """T2-D7 invariant preserved: only the start-time signature is
    memoized. The registry file (and therefore session_id) is read
    fresh on every call, so a session_id change under the same pid +
    same start signature is visible on the very next call."""
    _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: "sig-fixed")
    _as_window(monkeypatch, 6001)

    assert sr.write_session("stem-first", claude_pid=6001) is True
    assert sr.current_window_session() == "stem-first"  # populates cache

    # rewrite the registry under the SAME pid/signature — only the
    # session_id changes, exactly what happens across a /clear
    assert sr.write_session("stem-second", claude_pid=6001) is True
    assert sr.current_window_session() == "stem-second"


# ── has_active_session_window (G-3 groomer guard rail) ──────────────────


def test_has_active_session_window_empty_registry(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    assert sr.has_active_session_window() is False


def test_has_active_session_window_true_for_live_session(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "555.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stem-live",
                "claude_pid": 555,
                "claude_start_time": "sig",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    assert sr.has_active_session_window() is True


def test_has_active_session_window_false_for_dead_pid(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: False)
    d.mkdir(parents=True, exist_ok=True)
    (d / "556.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": "stem-dead",
                "claude_pid": 556,
                "claude_start_time": "sig",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    assert sr.has_active_session_window() is False


def test_has_active_session_window_false_for_tombstoned_entry(tmp_path, monkeypatch):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "557.json").write_text(
        json.dumps(
            {
                "v": 1,
                "session_id": None,
                "claude_pid": 557,
                "claude_start_time": "sig",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    assert sr.has_active_session_window() is False


def test_has_active_session_window_false_for_unknown_schema_version(
    tmp_path, monkeypatch
):
    d = _patch_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "558.json").write_text(
        json.dumps(
            {
                "v": 99,
                "session_id": "stem-future",
                "claude_pid": 558,
                "claude_start_time": "sig",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    assert sr.has_active_session_window() is False


def test_has_active_session_window_unreadable_dir_degrades_false(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sr, "registry_dir", lambda: tmp_path / "does-not-exist" / "nested"
    )
    assert sr.has_active_session_window() is False
