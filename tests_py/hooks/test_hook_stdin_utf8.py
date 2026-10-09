"""Issue #664: hooks decode the event JSON as UTF-8, whatever the locale.

Claude Code writes the hook event as UTF-8 bytes. On Windows a text-mode
``sys.stdin`` decodes with the locale code page (cp1252), so ``é`` arrives as
``Ã©``. This Mac cannot run Windows, so the cause is simulated: ``sys.stdin``
is an ``io.TextIOWrapper`` over the UTF-8 bytes with ``encoding="cp1252"``
and ``errors="surrogateescape"`` -- the exact decoding the issue measured.

source: CPython Doc/library/sys.rst (``sys.stdin``): on Windows, pipes and disk
files use the system locale encoding, the ANSI code page; issue #664.
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

from mcp_server.hooks import (
    agent_briefing,
    auto_recall,
    compaction_checkpoint,
    decision_gate,
    no_deps_gate,
    pipeline_impact_bump,
    post_commit_reindex,
    post_tool_capture,
    preemptive_context,
    session_lifecycle,
    session_start,
)

# Non-ASCII the issue reproduced: é, —, →, an emoji (0x8D continuation byte
# has no cp1252 mapping, so surrogateescape yields a lone surrogate).
TEXT = "supprimé — élève → 😍"
EVENT = {"tool_name": "Bash", "note": TEXT}


def _windows_stdin(monkeypatch: pytest.MonkeyPatch, event: dict[str, Any]) -> None:
    payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
    stream = io.TextIOWrapper(
        io.BytesIO(payload), encoding="cp1252", errors="surrogateescape"
    )
    monkeypatch.setattr(sys, "stdin", stream)


def _capture_process_event(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType
) -> list[Any]:
    seen: list[Any] = []
    monkeypatch.setattr(module, "process_event", seen.append)
    return seen


def _capture_evaluate(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> list[Any]:
    seen: list[Any] = []

    def evaluate(event: Any) -> int:
        seen.append(event)
        return 0

    monkeypatch.setattr(module, "evaluate", evaluate)
    return seen


def _run_post_tool_capture(seen: list[Any]) -> None:
    post_tool_capture.main(dispatch=seen.append)


def _run_session_lifecycle(monkeypatch: pytest.MonkeyPatch, seen: list[Any]) -> None:
    monkeypatch.setattr(session_lifecycle, "_tombstone_session_registry", lambda: None)
    monkeypatch.setattr(
        session_lifecycle, "_deregister_groomer_coordinator", lambda: None
    )
    monkeypatch.setattr(sys, "argv", ["session_lifecycle"])
    session_lifecycle.main()


def _run_session_start(seen: list[Any]) -> None:
    seen.append(session_start._read_event())


_PROCESS_EVENT_HOOKS: list[tuple[ModuleType, Callable[[], None]]] = [
    (agent_briefing, agent_briefing.main),
    (auto_recall, auto_recall.main),
    (compaction_checkpoint, compaction_checkpoint.main),
    (pipeline_impact_bump, pipeline_impact_bump.main),
    (post_commit_reindex, post_commit_reindex.main),
    (preemptive_context, preemptive_context.main),
]


@pytest.mark.parametrize(
    ("module", "main"),
    _PROCESS_EVENT_HOOKS,
    ids=[module.__name__.rsplit(".", 1)[1] for module, _ in _PROCESS_EVENT_HOOKS],
)
def test_process_event_hook_reads_utf8(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    main: Callable[[], None],
) -> None:
    _windows_stdin(monkeypatch, EVENT)
    seen = _capture_process_event(monkeypatch, module)
    main()
    assert seen == [EVENT]


@pytest.mark.parametrize("module", [decision_gate, no_deps_gate])
def test_gate_hook_reads_utf8(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType
) -> None:
    _windows_stdin(monkeypatch, EVENT)
    seen = _capture_evaluate(monkeypatch, module)
    assert module.main() == 0
    assert seen == [EVENT]


def test_post_tool_capture_reads_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    _windows_stdin(monkeypatch, EVENT)
    seen: list[Any] = []
    _run_post_tool_capture(seen)
    assert seen == [EVENT]


def test_session_lifecycle_reads_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    _windows_stdin(monkeypatch, EVENT)
    seen = _capture_process_event(monkeypatch, session_lifecycle)
    _run_session_lifecycle(monkeypatch, seen)
    assert seen == [EVENT]


def test_session_start_reads_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    _windows_stdin(monkeypatch, EVENT)
    seen: list[Any] = []
    _run_session_start(seen)
    assert seen == [EVENT]
