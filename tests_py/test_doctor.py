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
    SQLITE_CHECKS,
    _i10_config,
    _methodology_dir,
    _pg_driver,
    _python_version,
    _sqlite_store,
    active_checks,
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


class TestBackendAwareChecks:
    """active_checks() mirrors the launcher/hook backend resolution
    (sqlite-first install): SQLite installs must not fail four PG checks."""

    def test_sqlite_backend_selects_sqlite_list(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
        assert active_checks() is SQLITE_CHECKS

    def test_postgresql_backend_selects_pg_list(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
        assert active_checks() is CHECKS

    def test_sqlite_list_has_no_pg_checks(self):
        assert _pg_driver not in SQLITE_CHECKS
        assert _sqlite_store in SQLITE_CHECKS

    def test_sqlite_store_check_passes_on_fresh_store(self, tmp_path, monkeypatch):
        from mcp_server.infrastructure import memory_config

        monkeypatch.setenv(
            "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
        )
        memory_config.get_memory_settings.cache_clear()
        try:
            check = _sqlite_store()
        finally:
            memory_config.get_memory_settings.cache_clear()
        assert check.ok is True
        assert "memories" in check.detail
