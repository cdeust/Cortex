"""The auto-capture check against a log written by the real telemetry writer
(issue #660, ADR-1095): record -> publish_record -> JSONL -> capture_verdict, and
the damaged-file paths on a file the writer itself created."""

from __future__ import annotations

import time

import pytest

from mcp_server.core import telemetry
from mcp_server.doctor import _auto_capture
from mcp_server.doctor_capture import UndecodableLogError, capture_verdict

# source: fixture size; the verdict needs FAILURE_RUN (5) skips, one more is slack
SKIPS = 6


@pytest.fixture
def written_log(monkeypatch, tmp_path):
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    log = tmp_path / "methodology" / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", log)
    monkeypatch.setattr("mcp_server.doctor.CLAUDE_DIR", tmp_path)
    telemetry.record("capture_processed", latency_ms=1.0)
    for _ in range(SKIPS):
        telemetry.record("capture_skipped", latency_ms=1.0, ok=False, skipped=True)
    return log


def test_real_writer_output_is_judged_by_the_reader(written_log, tmp_path) -> None:
    verdict = capture_verdict(tmp_path, time.time())
    assert not verdict.ok
    assert f"{SKIPS} captures skipped since the last processed one" in verdict.detail
    assert "1 processed" in verdict.detail


def test_invalid_bytes_in_the_log_fail_the_check_naming_the_file(
    written_log, tmp_path
) -> None:
    with written_log.open("ab") as stream:
        stream.write(b"\xff\xfe garbage\n")
    with pytest.raises(UndecodableLogError, match="telemetry.jsonl is not valid UTF-8"):
        capture_verdict(tmp_path, time.time())
    check = _auto_capture()
    assert check.ok is False
    assert str(written_log) in check.detail and "not valid UTF-8" in check.detail


def test_invalid_bytes_in_the_rotated_generation_name_that_file(
    written_log, tmp_path
) -> None:
    rotated = written_log.with_name("telemetry.jsonl.1")
    rotated.write_bytes(b'{"ts": 1, "op": "x"}\n\xc3\x28\n')
    check = _auto_capture()
    assert check.ok is False and str(rotated) in check.detail


def test_a_directory_in_place_of_the_log_fails_the_real_check(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    monkeypatch.setattr("mcp_server.doctor.CLAUDE_DIR", tmp_path)
    (tmp_path / "methodology" / "telemetry.jsonl").mkdir(parents=True)
    check = _auto_capture()
    assert check.ok is False and "cannot read the evidence" in check.detail
