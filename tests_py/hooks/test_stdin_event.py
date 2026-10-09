"""The one stdin reader (issue #664): strict UTF-8, one place, no bypass.

source: issue #664; https://docs.python.org/3/library/sys.html#sys.stdin
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mcp_server.hooks import entry, session_start
from mcp_server.hooks.stdin_event import (
    HookStdinDecodeError,
    install_event_stdin,
    read_event_text,
)

ROOT = Path(__file__).resolve().parents[2]
TEXT = '{"t": "supprimé — élève → 😍"}'


def _cp1252_pipe(data: bytes) -> io.TextIOWrapper:
    return io.TextIOWrapper(
        io.BytesIO(data), encoding="cp1252", errors="surrogateescape"
    )


def test_reads_utf8_bytes_whatever_the_stream_encoding(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(TEXT.encode("utf-8")))
    assert read_event_text() == TEXT


def test_invalid_utf8_is_a_hard_failure(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(b'{"t": "\xff\xfe"}'))
    with pytest.raises(HookStdinDecodeError, match="not valid UTF-8"):
        read_event_text()


def test_session_start_does_not_swallow_a_decode_failure(monkeypatch) -> None:
    """``_read_event`` degrades malformed JSON to {}; undecodable bytes are not JSON
    damage but lost data, so the failure must reach the launcher's report."""
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(b"\xff\xfe"))
    with pytest.raises(HookStdinDecodeError):
        session_start._read_event()


def test_install_event_stdin_round_trips_under_any_locale(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(b""))
    install_event_stdin(TEXT)
    assert read_event_text() == TEXT


def test_entry_main_decodes_the_event_as_utf8(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["hypermnesia-mcp-hook", "preemptive_context"])
    monkeypatch.setattr(entry, "prepare_environment", lambda environ: None)
    monkeypatch.setattr(entry, "resolve_auto_backend", lambda environ: None)
    monkeypatch.setattr(
        entry, "run_all", lambda module, payloads, name: seen.append(payloads) or 0
    )
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(TEXT.encode("utf-8")))
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 0
    assert [json.loads(p) for p in seen[0]] == [json.loads(TEXT)]


def _load_session_queue() -> ModuleType:
    path = ROOT / "plugins" / "hypermnesia-mcp-codex" / "scripts" / "session_queue.py"
    spec = importlib.util.spec_from_file_location("codex_session_queue", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_session_queue_intake_decodes_utf8(monkeypatch, tmp_path) -> None:
    queue = _load_session_queue()
    seen: list[object] = []
    monkeypatch.setattr(queue, "queue_root", lambda: tmp_path)
    monkeypatch.setattr(queue, "enqueue", lambda root, event: seen.append(event))
    monkeypatch.setattr(sys, "argv", ["session_queue.py", "intake"])
    monkeypatch.setattr(sys, "stdin", _cp1252_pipe(TEXT.encode("utf-8")))
    queue.main()
    assert seen == [json.loads(TEXT)]
