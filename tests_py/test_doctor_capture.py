"""``check_setup`` / ``python -m mcp_server.doctor`` judge auto-capture from the
telemetry log and the spool (issue #660).

The end-to-end case (the real ``check_setup`` handler) is in
``tests_py/handlers/test_check_setup_capture.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_server.doctor import CHECKS, SQLITE_CHECKS, _auto_capture
from mcp_server.doctor_capture import capture_verdict, read_events
from mcp_server.infrastructure import capture_spool

REPO = Path(__file__).resolve().parents[1]
# source: arbitrary fixture clock (the verdict depends only on differences)
NOW = 2_000_000_000.0


def _log(root: Path, rows: list[tuple[float, str]], name: str = "telemetry.jsonl"):
    directory = root / "methodology"
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": ts, "op": op, "ok": False}) for ts, op in rows]
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)


def test_both_backends_run_the_check_as_required() -> None:
    assert _auto_capture in CHECKS and _auto_capture in SQLITE_CHECKS


def test_no_telemetry_file_is_no_evidence_and_ok(tmp_path) -> None:
    assert capture_verdict(tmp_path, NOW).ok


def test_rotated_generation_is_read_before_the_live_one(tmp_path) -> None:
    _log(tmp_path, [(NOW - 50, "capture_processed")], "telemetry.jsonl.1")
    _log(tmp_path, [(NOW - 10 + i, "capture_skipped") for i in range(5)])
    events, malformed = read_events(tmp_path / "methodology" / "telemetry.jsonl")
    assert [op for _, op in events][0] == "capture_processed" and malformed == 0
    v = capture_verdict(tmp_path, NOW)
    assert not v.ok and "5 captures skipped since the last processed" in v.detail


def test_malformed_lines_are_counted_and_reported_not_hidden(tmp_path) -> None:
    _log(tmp_path, [(NOW - 5, "capture_processed")])
    path = tmp_path / "methodology" / "telemetry.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write('not json\n{"op": "capture_skipped"}\n[1]\n')
    v = capture_verdict(tmp_path, NOW)
    assert v.ok and "3 unreadable telemetry line(s) ignored" in v.detail


def test_a_stale_pending_spool_file_fails_the_check(tmp_path) -> None:
    spool = capture_spool.spool_directory(tmp_path)
    stale = capture_spool.write(spool, {"fixture": 1})
    old = NOW - capture_spool.STALL_SECONDS - 5
    os.utime(stale, (old, old))
    (spool / "x.json.rejected").write_text("{}")
    v = capture_verdict(tmp_path, NOW)
    assert not v.ok and "not being drained" in v.detail and "1 rejected" in v.detail


def test_the_check_creates_no_state(tmp_path) -> None:
    capture_verdict(tmp_path, NOW)
    assert list(tmp_path.iterdir()) == []


def test_disabled_telemetry_is_reported_as_unverifiable(tmp_path, monkeypatch) -> None:
    _log(tmp_path, [(NOW - 5, "capture_skipped")])
    monkeypatch.setenv("CORTEX_TELEMETRY_DISABLED", "1")
    v = capture_verdict(tmp_path, NOW)
    assert v.ok and v.detail.startswith("unverifiable")


def test_unreadable_evidence_is_a_failed_check_not_a_pass(
    monkeypatch, tmp_path
) -> None:
    def boom(*_a, **_k):
        raise PermissionError("fixture denied")

    monkeypatch.setattr("mcp_server.doctor.capture_verdict", boom)
    check = _auto_capture()
    assert check.ok is False and "fixture denied" in check.detail


def test_a_telemetry_log_that_is_a_directory_raises_to_the_check(tmp_path) -> None:
    (tmp_path / "methodology" / "telemetry.jsonl").mkdir(parents=True)
    with pytest.raises(OSError):
        capture_verdict(tmp_path, NOW)
