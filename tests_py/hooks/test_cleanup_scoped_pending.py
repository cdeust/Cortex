"""Scoped host pending records and interruption recovery. source: ADR-1092"""

import importlib
import json
from types import SimpleNamespace

import pytest

from tests_py.hooks.test_cleanup_transcripts import SID, artifact
from tests_py.hooks.test_cleanup_transcripts import purgers as purgers


def test_claude_host_import_keeps_old_scope_and_new_intake(
    purgers, tmp_path, monkeypatch
):
    claude, _ = purgers
    hooks = importlib.import_module("host_cleanup")
    intake = importlib.import_module("cleanup_intake")
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "new"))
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "new-tmp"))
    args = SimpleNamespace(
        host="claude",
        session=SID,
        state=str(tmp_path / "state.json"),
        event="SessionEnd",
    )
    intake.record_end(args, {})
    ledger = tmp_path / "ended-sessions.json"
    old = {"host": None, "tasks": False, "scope": {"home": "/old", "root": "/old/tmp"}}
    with hooks.host_registry(ledger) as pending:
        pending[SID] = old
    hooks.import_ended(args)
    with hooks.host_registry(ledger) as pending:
        assert pending[SID] == old
    assert len(intake.read_pending(args.state, "host")) == 1


def test_claude_end_records_exact_roots_for_retry(purgers, tmp_path):
    claude, _ = purgers
    scratch = artifact(tmp_path / "tmp", f"project/{SID}/tasks/file")
    pending = {}
    claude.end_session(
        pending,
        (tmp_path, tmp_path / "tmp"),
        SID,
        {"guard": lambda p: None, "host": None},
    )
    assert not scratch.exists()
    assert pending[SID]["scope"] == claude.pending_scope(tmp_path, tmp_path / "tmp")


def test_claude_interrupted_end_keeps_durable_pending(purgers, tmp_path, monkeypatch):
    claude, _ = purgers
    hooks = importlib.import_module("host_cleanup")
    intake = importlib.import_module("cleanup_intake")
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "tmp"))
    args = SimpleNamespace(
        host="claude",
        session=SID,
        state=str(tmp_path / "state.json"),
        event="SessionEnd",
    )
    intake.record_end(args, {})

    def interrupted(*args, **kwargs):
        raise RuntimeError("simulated interruption during end cleanup")

    monkeypatch.setattr(claude, "end_session", interrupted)
    monkeypatch.setattr(claude, "host_pid", lambda: None)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        hooks.after_hook(args, {}, {})
    with hooks.host_registry(tmp_path / "ended-sessions.json") as pending:
        assert SID in pending


@pytest.mark.parametrize("event", ["SessionStart", "SessionEnd"])
def test_codex_same_session_different_roots_keeps_original_pending(
    purgers, tmp_path, monkeypatch, event
):
    _, codex = purgers
    registry = importlib.import_module("host_cleanup").host_registry
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "original"))
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    args = SimpleNamespace(
        session=SID, event="SessionEnd", state=str(tmp_path / "ledger.json")
    )
    codex.settle(args, registry, lambda p: None)
    ledger = tmp_path / "codex-ended-sessions.json"
    before = json.loads(ledger.read_text())
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "different"))
    args.event = event
    codex.settle(args, registry, lambda p: None)
    assert json.loads(ledger.read_text()) == before
