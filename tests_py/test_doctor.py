"""Tests for the `cortex doctor` diagnostic CLI.

Covers the individual check functions without requiring a live PG —
connection checks are skipped when DATABASE_URL is absent so the test
suite stays hermetic.

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness).
"""

from __future__ import annotations


from mcp_server.doctor import (
    CHECKS,
    _i10_config,
    _methodology_dir,
    _pg_driver,
    _python_version,
    run,
)


class TestIndividualChecks:
    def test_python_version_passes_on_supported_runtime(self):
        check = _python_version()
        # This test suite requires 3.10+ anyway
        assert check.ok is True

    def test_pg_driver_passes_in_dev_env(self):
        check = _pg_driver()
        assert check.ok is True  # dev env has postgresql extras installed

    def test_i10_config_reports_capacity(self):
        check = _i10_config()
        assert check.ok is True
        assert "interactive=" in check.detail
        assert "batch=" in check.detail

    def test_methodology_dir_creates_if_missing(self, tmp_path, monkeypatch):
        # Point HOME at tmp so we don't touch ~/.claude for real
        monkeypatch.setenv("HOME", str(tmp_path))
        check = _methodology_dir()
        assert check.ok is True
        assert (tmp_path / ".claude" / "methodology").exists()


class TestRunReportFormat:
    def test_run_returns_int(self, capsys):
        rc = run()
        assert isinstance(rc, int)
        # With DATABASE_URL set by the surrounding harness, should be 0
        out = capsys.readouterr().out
        assert "Cortex doctor" in out

    def test_check_registry_nonempty(self):
        assert len(CHECKS) >= 5
        for c in CHECKS:
            assert callable(c)
