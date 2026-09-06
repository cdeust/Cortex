"""Count actual stdout bytes after encoding, errors policy, and CRLF expansion."""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

from mcp_server.core import telemetry
from mcp_server.hooks._telemetry import observe_hook


@pytest.mark.parametrize("newline", [None, "\r\n", ""])
def test_observer_counts_binary_output_after_text_transformations(
    newline, tmp_path, monkeypatch
):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", log)
    sink = io.BytesIO()
    stream = io.TextIOWrapper(sink, encoding="utf-8", errors="replace", newline=newline)
    monkeypatch.setattr(sys, "stdout", stream)
    original_write = sink.write
    stream.write("previous output\n")

    @observe_hook("session_start")
    def emit():
        print("café\n\ud800")

    emit()
    # source: TextIOWrapper newline=None translates LF to os.linesep.
    translated = os.linesep if newline is None else newline or "\n"
    expected = "café\n?\n".replace("\n", translated).encode("utf-8")
    sample = json.loads(log.read_text())
    assert sink.getvalue().endswith(expected)
    assert sample["bytes_out"] == len(expected)
    assert sample["ok"] is True
    assert sys.stdout is stream
    assert sink.write == original_write
    stream.detach()


def test_flush_failure_does_not_replace_original_exception(
    tmp_path, monkeypatch, caplog
):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", log)
    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", stream)
    failure = RuntimeError("original failure")

    @observe_hook("auto_recall")
    def emit():
        print("partial output")
        stream.close()
        raise failure

    with pytest.raises(RuntimeError) as caught:
        emit()
    assert caught.value is failure
    assert "Cannot flush failed hook output" in caplog.text
    assert json.loads(log.read_text())["ok"] is False


def test_binary_stdout_is_restored_after_hook_exception(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", log)
    sink = io.BytesIO()
    stream = io.TextIOWrapper(sink, encoding="utf-8", newline="\r\n")
    monkeypatch.setattr(sys, "stdout", stream)
    original_write = sink.write
    failure = RuntimeError("original failure")

    @observe_hook("auto_recall")
    def emit():
        print("déjà émis")
        raise failure

    with pytest.raises(RuntimeError) as caught:
        emit()
    sample = json.loads(log.read_text())
    assert caught.value is failure
    assert sample["bytes_out"] == len(sink.getvalue()) > 0
    assert sample["ok"] is False
    assert sink.write == original_write
    stream.detach()
