"""Retention contract on the existing purgers. source: ADR-1092"""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "plugins/hypermnesia-mcp-codex/scripts"
SID = "1824c7e3-e1e4-4a30-942d-0d65f2f78745"
OTHER = "2824c7e3-e1e4-4a30-942d-0d65f2f78745"


@pytest.fixture
def purgers(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.delenv("CORTEX_CLEANUP_TRANSCRIPTS", raising=False)
    return tuple(importlib.import_module(n) for n in ("session_purge", "codex_purge"))


def artifact(root, path, content="retained transcript"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_claude_default_preserves_resume_data_at_push_and_end(purgers, tmp_path):
    claude, _ = purgers
    home, temp = tmp_path / "claude", tmp_path / "tmp"
    paths = [
        artifact(home, p)
        for p in (
            f"projects/project/{SID}.jsonl",
            f"projects/project/{SID}/subagents/a.jsonl",
            f"file-history/{SID}/file",
        )
    ]
    scratch = artifact(temp, f"project/{SID}/scratchpad/disposable")
    claude.purge_now((home, temp), SID, lambda path: None)
    claude.purge_ended(
        (home, temp),
        SID,
        lambda path: None,
        wait=lambda: pytest.fail("retention must not wait for a reader"),
    )
    assert not scratch.exists()
    assert [p.read_text() for p in paths] == ["retained transcript"] * len(paths)


def test_claude_delete_requires_opt_in_and_reader_completion(
    purgers, tmp_path, monkeypatch
):
    claude, _ = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    transcript = artifact(tmp_path, f"projects/project/{SID}.jsonl")
    result = claude.purge_ended(
        (tmp_path, tmp_path / "tmp"), SID, lambda p: None, wait=lambda: False
    )
    assert transcript.exists()
    assert any("protected" in r for r in result)
    claude.purge_ended(
        (tmp_path, tmp_path / "tmp"), SID, lambda p: None, wait=lambda: True
    )
    assert not transcript.exists()


def test_codex_default_keeps_transcript_and_cleans_runtime_files(purgers, tmp_path):
    _, codex = purgers
    transcript = artifact(tmp_path, f"sessions/2026/09/26/rollout-test-{SID}.jsonl")
    snapshot = artifact(tmp_path, f"shell_snapshots/{SID}.123.sh")
    codex.purge((tmp_path, tmp_path / "queue"), SID, lambda path: None)
    assert transcript.read_text() == "retained transcript"
    assert not snapshot.exists()


def test_codex_opt_in_needs_fresh_matching_receipt(purgers, tmp_path, monkeypatch):
    _, codex = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    transcript = artifact(tmp_path, f"sessions/2026/09/26/rollout-test-{SID}.jsonl")
    queue = tmp_path / "queue"
    codex.purge((tmp_path, queue), SID, lambda path: None)
    assert transcript.exists()
    key = codex.hashlib.sha256(SID.encode()).hexdigest()
    artifact(
        queue,
        key + ".json",
        json.dumps({"event": {"session_id": SID, "transcript_path": str(transcript)}}),
    )
    codex.purge((tmp_path, queue), SID, lambda path: None)
    assert not transcript.exists()


def test_codex_end_defers_io_to_next_event(purgers, tmp_path, monkeypatch):
    _, codex = purgers
    registry = importlib.import_module("host_cleanup").host_registry
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    snapshot = artifact(tmp_path, f"shell_snapshots/{SID}.sh")
    args = SimpleNamespace(
        session=SID, event="SessionEnd", state=tmp_path / "state.json"
    )
    codex.settle(args, registry, lambda p: pytest.fail("end must defer process checks"))
    assert snapshot.exists()
    args.session, args.event = OTHER, "SessionStart"
    codex.settle(args, registry, lambda p: None)
    assert not snapshot.exists()


def test_invalid_opt_in_is_rejected_before_removal(purgers, monkeypatch):
    policy = importlib.import_module("transcript_policy")
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "deleete")
    with pytest.raises(ValueError, match="keep or delete"):
        policy.delete_enabled()


def test_claude_symlink_ancestor_is_protected(purgers, tmp_path):
    claude, _ = purgers
    outside = tmp_path / "outside"
    target = artifact(outside, f"{SID}/scratchpad/file")
    root = tmp_path / "temp"
    root.mkdir()
    (root / "project").symlink_to(outside, target_is_directory=True)
    results = claude.purge_now((tmp_path / "home", root), SID, lambda path: None)
    assert target.exists()
    assert any(r.get("protected") == "symlink parent" for r in results)


def test_claude_nested_transcripts_wait_for_reader(purgers, tmp_path, monkeypatch):
    claude, _ = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    nested = artifact(tmp_path, f"projects/project/{SID}/subagents/a.jsonl")
    claude.purge_ended(
        (tmp_path, tmp_path / "tmp"), SID, lambda p: None, wait=lambda: False
    )
    assert nested.read_text() == "retained transcript"


def test_claude_retry_keeps_main_and_nested_while_reader_runs(
    purgers, tmp_path, monkeypatch
):
    claude, _ = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    monkeypatch.setattr(claude, "reader_running", lambda: True)
    paths = [
        artifact(tmp_path, p)
        for p in (
            f"projects/project/{SID}.jsonl",
            f"projects/project/{SID}/subagents/a.jsonl",
        )
    ]
    pending = {
        SID: {
            "host": None,
            "tasks": False,
            "scope": {
                "home": str(tmp_path.resolve()),
                "root": str((tmp_path / "tmp").resolve()),
            },
        }
    }
    claude.retry_ended(
        pending, (tmp_path, tmp_path / "tmp"), OTHER, {"guard": lambda p: None}
    )
    assert all(p.exists() for p in paths)
    assert SID in pending


def test_claude_retry_does_not_apply_old_owner_to_new_roots(
    purgers, tmp_path, monkeypatch
):
    claude, _ = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    transcript = artifact(tmp_path, f"projects/project/{SID}.jsonl")
    for old_record in (
        {"host": None, "tasks": False},
        {"host": None, "tasks": False, "scope": {"home": "/old", "root": "/old/tmp"}},
    ):
        pending = {SID: old_record}
        result = claude.retry_ended(
            pending, (tmp_path, tmp_path / "tmp"), OTHER, {"guard": lambda p: None}
        )
        assert transcript.exists()
        assert SID in pending
        assert any("protected" in r for r in result)


def test_claude_push_keeps_nested_and_main_during_reader(
    purgers, tmp_path, monkeypatch
):
    claude, _ = purgers
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    monkeypatch.setattr(claude, "reader_running", lambda: True)
    paths = [
        artifact(tmp_path, p)
        for p in (
            f"projects/project/{SID}.jsonl",
            f"projects/project/{SID}/subagents/a.jsonl",
        )
    ]
    claude.purge_now((tmp_path, tmp_path / "tmp"), SID, lambda p: None)
    assert all(p.exists() for p in paths)


def test_claude_reader_probe_errors_fail_closed(purgers, monkeypatch):
    claude, _ = purgers
    monkeypatch.setattr(
        claude.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stderr="", stdout=""),
    )
    assert claude.reader_running()
