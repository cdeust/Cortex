"""Hook telemetry measures emitted text without changing CLI behavior."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from types import SimpleNamespace

import pytest

from mcp_server.core import telemetry
from mcp_server.handlers import query_methodology
from mcp_server.hooks import _telemetry, auto_recall, session_start
from mcp_server.shared.telemetry_context import (
    count_reranked,
    operation_metrics,
    retrieval_metrics,
    set_retrieval_tier,
)


@pytest.fixture(autouse=True)
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.set_exporter(None)
    telemetry.reset()
    yield path
    telemetry.set_exporter(None)
    telemetry.reset()


def _sample(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_counting_output_counts_only_text_accepted_by_stream():
    accepted = []
    flushed = []

    def partial_write(text):
        accepted.append(text[:1])
        return 1

    stream = SimpleNamespace(write=partial_write, flush=lambda: flushed.append(True))
    output = _telemetry._CountingOutput(stream)
    assert output.write("été") == 1
    output.flush()
    assert accepted == ["é"]
    assert output.bytes_out == len("é".encode("utf-8"))
    assert flushed == [True]


def test_counting_output_preserves_write_failures():
    stream = io.StringIO()
    stream.close()
    output = _telemetry._CountingOutput(stream)
    with pytest.raises(ValueError, match="closed file"):
        output.write("mémoire")
    assert output.bytes_out == 0


def test_observer_measures_complete_utf8_output_and_duration(
    telemetry_log, monkeypatch, capsys
):
    clock = iter((5.0, 5.25))
    monkeypatch.setattr(_telemetry.time, "perf_counter", lambda: next(clock))
    original_stdout = sys.stdout

    @_telemetry.observe_hook("session_start")
    def hook():
        print("Décision 🧠", end=" ", flush=True)
        print("⟦rcpt:7⟧")
        print("\nSources externes : mémoire")
        print("diagnostic", file=sys.stderr)

    hook()
    assert sys.stdout is original_stdout
    out, err = capsys.readouterr()
    assert out == "Décision 🧠 ⟦rcpt:7⟧\n\nSources externes : mémoire\n"
    assert err == "diagnostic\n"
    sample = _sample(telemetry_log)
    assert sample["bytes_out"] == len(out.encode("utf-8"))
    assert sample["latency_ms"] == 250.0
    assert sample["ok"] is True


@pytest.mark.parametrize("code", [None, 0, 1, "failure"])
def test_exit_code_is_preserved_and_recorded(code, telemetry_log, capsys):
    original_stdout = sys.stdout
    failure = SystemExit(code)

    @_telemetry.observe_hook("auto_recall")
    def hook():
        print("déjà émis")
        raise failure

    with pytest.raises(SystemExit) as caught:
        hook()
    assert caught.value is failure
    assert sys.stdout is original_stdout
    sample = _sample(telemetry_log)
    assert sample["ok"] is (code is None or code == 0)
    assert sample["bytes_out"] == len(capsys.readouterr().out.encode("utf-8"))


def test_exception_records_partial_output_and_remains_visible(telemetry_log, capsys):
    original_stdout = sys.stdout
    failure = RuntimeError("hook failed")

    @_telemetry.observe_hook("session_start")
    def hook():
        print("émission partielle")
        raise failure

    with pytest.raises(RuntimeError) as caught:
        hook()
    assert caught.value is failure
    assert sys.stdout is original_stdout
    sample = _sample(telemetry_log)
    assert sample["ok"] is False
    assert sample["bytes_out"] == len(capsys.readouterr().out.encode("utf-8"))


def test_metrics_are_isolated_and_recorded_before_context_exit(telemetry_log):
    @_telemetry.observe_hook("auto_recall")
    def hook():
        assert retrieval_metrics().tier is None
        assert retrieval_metrics().reranked_count == 0
        set_retrieval_tier("hook")
        count_reranked(2)

    with operation_metrics():
        set_retrieval_tier("outer")
        count_reranked(3)
        hook()
        assert retrieval_metrics().tier == "outer"
        assert retrieval_metrics().reranked_count == 3
    sample = _sample(telemetry_log)
    assert sample["tier"] == "hook"
    assert sample["reranked_count"] == 2
    assert sample["bytes_out"] == 0
    assert sample["ok"] is True


def test_disabled_telemetry_preserves_output(telemetry_log, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_TELEMETRY_DISABLED", "1")

    @_telemetry.observe_hook("auto_recall")
    def hook():
        print("mémoire")

    hook()
    assert capsys.readouterr().out == "mémoire\n"
    assert not telemetry_log.exists()
    assert telemetry.snapshot() == {}


def test_log_write_failure_does_not_break_hook(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(telemetry, "_LOG_PATH", tmp_path)

    @_telemetry.observe_hook("auto_recall")
    def hook():
        print("mémoire")

    hook()
    assert capsys.readouterr().out == "mémoire\n"
    assert telemetry.snapshot()["auto_recall"]["ok"] == 1


def _patch_session_main(monkeypatch):
    for name in (
        "_refresh_session_registry",
        "_auto_wire_pipeline",
        "_maybe_background_reanalyze",
        "_maybe_background_consolidate",
    ):
        monkeypatch.setattr(session_start, name, lambda *args: None)
    values = {
        "_read_event": {},
        "_backend_is_sqlite": False,
        "_connect_pg": SimpleNamespace(close=lambda: None),
        "_count_memories": 1,
        "_fetch_anchors": [{"id": 1, "content": "Décision 🧠"}],
        "_fetch_hot_memories": [],
        "_fetch_team_decisions": [],
        "_fetch_checkpoint": None,
        "_count_pending_curations": 0,
        "_fetch_grooming_staleness": [],
        "_emit_banner_receipt": 7,
        "_has_sentence_transformers": True,
        "_detect_external_sources": [],
    }
    for name, value in values.items():
        monkeypatch.setattr(session_start, name, lambda *args, value=value: value)


def test_session_main_counts_banner_receipt_and_external_sources(
    telemetry_log, monkeypatch, capsys
):
    _patch_session_main(monkeypatch)
    monkeypatch.setattr(
        session_start,
        "_detect_external_sources",
        lambda: [{"name": "Mémoire externe", "path": "/fixture/été", "count": 1}],
    )

    session_start.main()

    out = capsys.readouterr().out
    assert "Décision 🧠" in out
    assert "⟦rcpt:7⟧" in out
    assert "Mémoire externe" in out
    sample = _sample(telemetry_log)
    assert sample["op"] == "session_start"
    assert sample["bytes_out"] == len(out.encode("utf-8"))
    assert sample["ok"] is True


def _patch_auto_main(monkeypatch):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"prompt":"remember this decision"}')
    )
    monkeypatch.setattr(auto_recall, "_refresh_session_registry", lambda event: None)
    monkeypatch.setattr(auto_recall, "_backend_is_sqlite", lambda: False)
    monkeypatch.setattr(
        auto_recall, "_connect", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        auto_recall,
        "_recall_memories",
        lambda conn, query: [{"id": 1, "content": "Décision 🧠"}],
    )
    monkeypatch.setattr(auto_recall, "emit_hook_receipt", lambda *args, **kwargs: 9)


def test_isolated_session_records_all_context_operations(
    telemetry_log, monkeypatch, capsys
):
    monkeypatch.setattr(query_methodology, "load_profiles", lambda: {})
    monkeypatch.setattr(query_methodology, "_try_get_memory_store", lambda: None)
    monkeypatch.setattr(query_methodology, "_bounded", lambda response: response)
    response = asyncio.run(
        query_methodology.handler({"cwd": str(telemetry_log.parent)})
    )
    assert response["coldStart"] is True
    _patch_session_main(monkeypatch)
    session_start.main()
    banner = capsys.readouterr().out
    _patch_auto_main(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        auto_recall.main()
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "Décision 🧠" in out
    assert "⟦rcpt:9⟧" in out
    samples = [json.loads(line) for line in telemetry_log.read_text().splitlines()]
    assert [sample["op"] for sample in samples] == [
        "query_methodology",
        "session_start",
        "auto_recall",
    ]
    assert samples[0]["bytes_out"] > 0
    assert samples[1]["bytes_out"] == len(banner.encode("utf-8")) > 0
    assert samples[2]["bytes_out"] == len(out.encode("utf-8")) > 0
    assert all(sample["ok"] for sample in samples)


@pytest.mark.parametrize("raw", ["", "{bad json", '{"prompt":"ok"}'])
def test_auto_recall_main_silent_exits_are_recorded(
    raw, telemetry_log, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(auto_recall, "_refresh_session_registry", lambda event: None)

    with pytest.raises(SystemExit) as caught:
        auto_recall.main()

    assert caught.value.code == 0
    assert capsys.readouterr().out == ""
    sample = _sample(telemetry_log)
    assert sample["op"] == "auto_recall"
    assert sample["bytes_out"] == 0
    assert sample["ok"] is True
