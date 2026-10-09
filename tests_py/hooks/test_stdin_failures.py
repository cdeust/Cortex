"""Every reader reports undecodable stdin through the hook error contract.

Invalid UTF-8 is a hard, reported failure (issue #664), never a replacement,
and it never blocks: exit 1 for every hook, the PreToolUse gates included
(ADR-1060: a read or parse failure never blocks a tool call).
"""

from __future__ import annotations

import importlib.util
import io
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from mcp_server.hooks import (
    agent_briefing,
    auto_recall,
    compaction_checkpoint,
    decision_gate,
    entry,
    no_deps_gate,
    pipeline_impact_bump,
    post_commit_reindex,
    post_tool_capture,
    preemptive_context,
    session_lifecycle,
    session_start,
)
from mcp_server.hooks.stdin_event import HookStdinDecodeError

ROOT = Path(__file__).resolve().parents[2]
BAD = b'{"note": "\xff\xfe"}'


def _bad_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.TextIOWrapper(
        io.BytesIO(BAD), encoding="cp1252", errors="surrogateescape"
    )
    monkeypatch.setattr(sys, "stdin", stream)


@pytest.mark.parametrize("name", sorted(entry.HOOK_MODULES))
def test_entry_reports_undecodable_stdin_with_exit_1_for_every_hook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["hypermnesia-mcp-hook", name])
    monkeypatch.setattr(entry, "prepare_environment", lambda environ: None)
    monkeypatch.setattr(entry, "resolve_auto_backend", lambda environ: None)
    monkeypatch.setattr(entry, "run_all", pytest.fail)
    _bad_stdin(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith(f"[hypermnesia-mcp-hook] mcp_server.hooks.{name}: ")
    assert "not valid UTF-8" in err


@pytest.mark.parametrize("module", [decision_gate, no_deps_gate])
def test_gates_keep_their_non_blocking_contract_on_undecodable_stdin(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType
) -> None:
    """The failure is loud (it reaches the launcher's report) and never exit 2."""
    _bad_stdin(monkeypatch)
    monkeypatch.setattr(module, "evaluate", pytest.fail)
    with pytest.raises(HookStdinDecodeError):
        module.main()


def _session_lifecycle_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_lifecycle, "_tombstone_session_registry", lambda: None)
    monkeypatch.setattr(
        session_lifecycle, "_deregister_groomer_coordinator", lambda: None
    )
    monkeypatch.setattr(sys, "argv", ["session_lifecycle"])
    session_lifecycle.main()


_LOGGING_HOOKS: list[tuple[ModuleType, Callable[[pytest.MonkeyPatch], Any]]] = [
    (agent_briefing, lambda mp: agent_briefing.main()),
    (auto_recall, lambda mp: auto_recall.main()),
    (compaction_checkpoint, lambda mp: compaction_checkpoint.main()),
    (pipeline_impact_bump, lambda mp: pipeline_impact_bump.main()),
    (post_commit_reindex, lambda mp: post_commit_reindex.main()),
    (post_tool_capture, lambda mp: post_tool_capture.main()),
    (preemptive_context, lambda mp: preemptive_context.main()),
    (session_lifecycle, _session_lifecycle_main),
    (session_start, lambda mp: session_start._read_event()),
]


@pytest.mark.parametrize(
    ("module", "call"),
    _LOGGING_HOOKS,
    ids=[module.__name__.rsplit(".", 1)[1] for module, _ in _LOGGING_HOOKS],
)
def test_hook_logs_then_fails_on_undecodable_stdin(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    call: Callable[[pytest.MonkeyPatch], Any],
) -> None:
    logged: list[str] = []
    monkeypatch.setattr(module, "_log", logged.append)
    _bad_stdin(monkeypatch)
    with pytest.raises(HookStdinDecodeError):
        call(monkeypatch)
    assert len(logged) == 1 and "not valid UTF-8" in logged[0]


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_capture_reports_undecodable_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CORTEX_HEADLESS_AUTHORING_CHILD", raising=False)
    capture = _load(ROOT / "scripts" / "launcher_capture.py", "launcher_capture_t")
    _bad_stdin(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        capture.skip_capture()
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("[cortex-launcher] Failed to run mcp_server.hooks.post_tool")
    assert "not valid UTF-8" in err


def test_codex_session_queue_intake_reports_undecodable_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    queue = _load(
        ROOT / "plugins" / "hypermnesia-mcp-codex" / "scripts" / "session_queue.py",
        "session_queue_t",
    )
    monkeypatch.setattr(queue, "queue_root", lambda: tmp_path)
    monkeypatch.setattr(queue, "enqueue", pytest.fail)
    monkeypatch.setattr(sys, "argv", ["session_queue.py", "intake"])
    _bad_stdin(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        queue.main()
    assert caught.value.code == 1
    assert "not valid UTF-8" in capsys.readouterr().err
