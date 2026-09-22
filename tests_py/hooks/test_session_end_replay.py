"""Crash replay must not repeat log/profile effects. source: ADR-1084"""

import os
from unittest.mock import patch

import pytest

from mcp_server.hooks import session_lifecycle as hook
from mcp_server.infrastructure.profile_store import save_profile, load_profile
from mcp_server.infrastructure.session_store import load_session_log
from mcp_server.infrastructure import profile_store, session_store


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv(
        "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
    )
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    assert os.environ["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    monkeypatch.setattr(hook, "METHODOLOGY_DIR", tmp_path / "methodology")
    monkeypatch.setattr(session_store, "SESSION_LOG_PATH", tmp_path / "sessions.json")
    monkeypatch.setattr(profile_store, "DOMAINS_DIR", tmp_path / "domains")
    monkeypatch.setattr(profile_store, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(profile_store, "PROFILES_PATH", tmp_path / "profiles.json")


def test_replay_after_profile_write_is_idempotent():
    save_profile("replay", {"projects": ["replay"], "sessionCount": 0})
    event = {"session_id": "replay-one", "project": "replay", "turn_count": 4}
    with patch.object(hook, "_spawn_consolidation", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError, match="crash"):
            hook.process_event(event)
    with patch.object(hook, "_spawn_consolidation"):
        hook.process_event(event)
    assert len(load_session_log()["sessions"]) == 1
    assert load_profile("replay")["sessionCount"] == 1


def test_replay_after_log_write_finishes_profile_once():
    save_profile("replay", {"projects": ["replay"], "sessionCount": 0})
    event = {"session_id": "replay-two", "project": "replay"}
    with patch.object(hook, "save_profile", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError, match="crash"):
            hook.process_event(event)
    with patch.object(hook, "_spawn_consolidation"):
        hook.process_event(event)
    assert len(load_session_log()["sessions"]) == 1
    assert load_profile("replay")["sessionCount"] == 1


@pytest.mark.parametrize("target", ["log", "profile"])
def test_corrupted_existing_state_is_not_acknowledged(target):
    save_profile("replay", {"projects": ["replay"], "sessionCount": 0})
    path = (
        session_store.SESSION_LOG_PATH
        if target == "log"
        else profile_store.DOMAINS_DIR / "replay.json"
    )
    path.write_text("{broken")
    with pytest.raises(ValueError), patch.object(hook, "_spawn_consolidation") as spawn:
        hook.process_event({"session_id": "corrupt", "project": "replay"})
    spawn.assert_not_called()
    assert path.read_text() == "{broken"


def test_concurrent_direct_callers_record_once(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys

    assert os.environ["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    root = tmp_path / "concurrent"
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(root))
    setup = (
        "from mcp_server.infrastructure.profile_store import save_profile; "
        "save_profile('replay', {'projects':['replay'], 'sessionCount':0})"
    )
    subprocess.run([sys.executable, "-c", setup], check=True)
    code = (
        "from mcp_server.hooks import session_lifecycle as h; "
        "h._spawn_consolidation=lambda **kw: None; "
        "print('ready',flush=True); input(); "
        "h.process_event({'session_id':'parallel','project':'replay'})"
    )
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    for worker in workers:
        assert worker.stdout.readline().strip() == "ready"
    for worker in workers:
        worker.stdin.write("go\n")
        worker.stdin.flush()
    assert [worker.wait() for worker in workers] == [0, 0]
    state = root / "methodology"
    assert len(json.loads((state / "session-log.json").read_text())["sessions"]) == 1
    assert json.loads((state / "domains/replay.json").read_text())["sessionCount"] == 1


def test_first_profile_directory_chain_is_durable(tmp_path):
    from mcp_server.infrastructure import file_io

    observed = []
    with patch.object(file_io, "_sync_directory", side_effect=observed.append):
        file_io.write_json(tmp_path / "new/domains/profile.json", {"sessionCount": 1})
    assert observed == [tmp_path, tmp_path / "new", tmp_path / "new/domains"]


def test_direct_cold_start_persists_methodology_directory(tmp_path, monkeypatch):
    from mcp_server.infrastructure import file_io

    root = tmp_path / "direct/methodology"
    monkeypatch.setattr(hook, "METHODOLOGY_DIR", root)
    observed = []
    with patch.object(file_io, "_sync_directory", side_effect=observed.append):
        with patch.object(hook, "_record_event"):
            hook.process_event({"session_id": "direct-cold"})
    assert observed == [tmp_path, tmp_path / "direct"]
