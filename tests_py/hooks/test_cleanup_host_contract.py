"""Shared manifest commands and Codex safety regressions. source: ADR-1092"""

import importlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/hypermnesia-mcp-codex/scripts"
SID = "1824c7e3-e1e4-4a30-942d-0d65f2f78745"
OTHER = "2824c7e3-e1e4-4a30-942d-0d65f2f78745"


def artifact(root, relative, content="resume data"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for key, value in {
        "HOME": tmp_path,
        "CODEX_HOME": tmp_path / "codex",
        "CORTEX_CLAUDE_DIR": tmp_path / ".claude",
        "CLAUDE_CODE_TMPDIR": tmp_path / "temp",
        "CLAUDE_PLUGIN_ROOT": ROOT,
        "PLUGIN_ROOT": SCRIPTS.parent,
        "CORTEX_CLEANUP_TRANSCRIPTS": "keep",
    }.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    return importlib.import_module("codex_purge")


def manifest_command(host, event):
    manifest = (
        ROOT / ".claude-plugin/plugin.json"
        if host == "claude"
        else SCRIPTS.parent / "hooks/hooks.json"
    )
    hooks = json.loads(manifest.read_text())["hooks"][event]
    commands = [
        hook["command"]
        for group in hooks
        for hook in group["hooks"]
        if "disk_hygiene.py" in hook["command"]
    ]
    assert len(commands) == 1
    return commands[0]


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("event", ["SessionStart", "PostToolUse", "Stop", "SessionEnd"])
def test_exact_manifest_command_accepts_native_payload(isolated, tmp_path, host, event):
    relative = (
        f".claude/projects/project/{SID}.jsonl"
        if host == "claude"
        else f"codex/sessions/2026/09/26/rollout-test-{SID}.jsonl"
    )
    transcript = artifact(tmp_path, relative)
    command = manifest_command(host, event)
    assert str(SCRIPTS / "disk_hygiene.py") in os.path.expandvars(command)
    result = subprocess.run(
        command,
        shell=True,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        input=json.dumps(
            {
                "session_id": SID,
                "hook_event_name": event,
                "cwd": str(tmp_path),
                "transcript_path": str(transcript),
                "tool_name": "exec_command",
                "tool_input": {"cmd": "true"},
                "reason": "clear",
            }
        ),
        env=dict(os.environ),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    output = json.loads(result.stdout)
    assert not isinstance(output, dict) or "protected" not in output
    if event == "SessionStart":
        assert output["hookSpecificOutput"]["hookEventName"] == event
    assert transcript.read_text() == "resume data"


def receipt(codex, transcript):
    _, queue = codex.roots()
    return artifact(
        queue,
        hashlib.sha256(SID.encode()).hexdigest() + ".json",
        json.dumps({"event": {"session_id": SID, "transcript_path": str(transcript)}}),
    )


def test_stale_receipt_cannot_delete_resumed_transcript(isolated, monkeypatch):
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    home, queue = isolated.roots()
    transcript = artifact(home, f"sessions/2026/09/26/rollout-test-{SID}.jsonl")
    completed = receipt(isolated, transcript)
    timestamp = completed.stat().st_mtime_ns + 1
    transcript.write_text("new resumed content")
    os.utime(transcript, ns=(timestamp, timestamp))
    result = isolated.purge((home, queue), SID, lambda path: None)
    assert any("protected" in item for item in result)
    assert transcript.read_text() == "new resumed content"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_durable_host_end_recovers_on_next_start(isolated, tmp_path, host):
    intake = importlib.import_module("cleanup_intake")
    cleanup = importlib.import_module("host_cleanup")
    args = SimpleNamespace(
        state=str(tmp_path / "ledger.json"), host=host, session=SID, event="SessionEnd"
    )
    relative = (
        f".claude/session-env/{SID}/scratch"
        if host == "claude"
        else f"codex/shell_snapshots/{SID}.sh"
    )
    scratch = artifact(tmp_path, relative)
    intake.record_end(args, {"cwd": str(tmp_path)})
    args.session, args.event = OTHER, "SessionStart"
    cleanup.after_hook(args, {}, {})
    assert not scratch.exists()
    assert not intake.read_pending(args.state, "host")
    assert intake.read_pending(args.state, "worktree")


@pytest.mark.parametrize("ended", [False, True])
def test_real_open_writer_lock_preserves_runtime_and_transcript(isolated, ended):
    home, queue = isolated.roots()
    lock = artifact(home, f"thread-writer-locks/{SID}.lock")
    snapshot = artifact(home, f"shell_snapshots/{SID}.123.sh")
    transcript = artifact(home, f"sessions/2026/09/26/rollout-test-{SID}.jsonl")
    guard = importlib.import_module("cleanup_processes").no_open_files
    with lock.open():
        result = isolated.purge((home, queue), SID, guard, ended=ended)
    assert any("active process" in item.get("protected", "") for item in result)
    assert snapshot.exists()
    assert transcript.exists()


def test_resume_cancels_pending_deletion(isolated, tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_CLEANUP_TRANSCRIPTS", "delete")
    home, _ = isolated.roots()
    transcript = artifact(home, f"sessions/2026/09/26/rollout-test-{SID}.jsonl")
    registry = importlib.import_module("host_cleanup").host_registry
    args = SimpleNamespace(
        session=SID, event="SessionEnd", state=tmp_path / "state.json"
    )
    isolated.settle(args, registry, lambda path: None)
    receipt(isolated, transcript)
    args.event = "SessionStart"
    isolated.settle(args, registry, lambda path: None)
    args.session = OTHER
    isolated.settle(args, registry, lambda path: None)
    assert transcript.exists()
    assert SID not in json.loads((tmp_path / "codex-ended-sessions.json").read_text())
