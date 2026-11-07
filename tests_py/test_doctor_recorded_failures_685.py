"""Issue #685: doctor and check_setup read the process-local failure counters."""

from __future__ import annotations

import asyncio

import pytest

from mcp_server import doctor
from mcp_server.handlers import check_setup
from mcp_server.observability import silent_failure


@pytest.fixture(autouse=True)
def _reset_failures():
    silent_failure.reset()
    yield
    silent_failure.reset()


def test_both_backend_lists_include_the_reader_last():
    assert doctor.CHECKS[-1].__name__ == "_recorded_failures"
    assert doctor.SQLITE_CHECKS[-1].__name__ == "_recorded_failures"


def test_check_setup_exposes_repeated_failure_count_and_last_error(monkeypatch):
    silent_failure.note("fixture.component", ValueError("first failure"))
    silent_failure.note("fixture.component", RuntimeError("latest failure"))
    before = silent_failure.status()
    monkeypatch.setattr(check_setup, "active_checks", lambda: [doctor.CHECKS[-1]])

    result = asyncio.run(check_setup.handler())

    assert result["ready"] is True
    assert result["fixes_needed"] == 0
    assert result["checks"][0]["optional"] is True
    detail = result["checks"][0]["detail"]
    assert "fixture.component" in detail
    assert "2 failure(s)" in detail
    assert "RuntimeError: latest failure" in detail
    assert silent_failure.status() == before


def test_doctor_prints_historical_warning_without_blocking_readiness(
    monkeypatch, capsys
):
    silent_failure.note("fixture.component", RuntimeError("probe failed"))
    monkeypatch.setattr(doctor, "active_checks", lambda: [doctor.CHECKS[-1]])

    assert doctor._run_full_check() == 0
    output = capsys.readouterr().out
    assert "[WARN]" in output
    assert "fixture.component" in output
    assert "RuntimeError: probe failed" in output


def test_reader_reports_process_scope_and_does_not_clear_history():
    check = doctor.CHECKS[-1]()
    assert check.ok
    assert "this process" in check.detail
    silent_failure.note("fixture.component", ValueError("persisted"))
    first = doctor.CHECKS[-1]()
    second = doctor.CHECKS[-1]()
    assert not first.ok and not second.ok
    assert first.detail == second.detail


def test_reader_redacts_secrets_and_sorts_components(monkeypatch):
    failures = {
        "z.component": {"count": 2, "last_error": "password=fixture-secret"},
        "a.component": {"count": 1, "last_error": "ordinary failure"},
    }
    monkeypatch.setattr(silent_failure, "status", lambda: failures)

    check = doctor._recorded_failures()

    assert check.optional and not check.ok
    assert "fixture-secret" not in check.detail
    assert "ordinary failure" in check.detail
    assert check.detail.startswith("a.component: 1 failure(s), ordinary failure; ")
    assert "z.component: 2 failure(s)" in check.detail
    assert failures["z.component"]["last_error"] == "password=fixture-secret"


@pytest.mark.parametrize("port", ["5432", "5432;", "invalid", "99999"])
def test_reader_redacts_url_errors_before_joining_components(monkeypatch, port):
    failures = {
        "a.component": {
            "count": 1,
            "last_error": f"connect postgresql://u:fixture-secret@db:{port}",
        },
        "z.component": {"count": 2, "last_error": "ordinary failure"},
    }
    monkeypatch.setattr(silent_failure, "status", lambda: failures)

    check = doctor._recorded_failures()

    assert check.optional and not check.ok
    assert "fixture-secret" not in check.detail
    assert f"postgresql://u:***@db:{port}; z.component" in check.detail
    assert "z.component: 2 failure(s), ordinary failure" in check.detail
