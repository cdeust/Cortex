"""Tests for `mcp_server.doctor._sqlite_vector_search`.

Split out of test_doctor.py to stay under its 300-line cap (source:
ADR-1089). sqlite-vec ships in every install's base package set now, so
absence or a load failure is a broken install: this check is required
(``optional=False``), not the degraded-mode probe issue #634 originally
shipped it as.
"""

from __future__ import annotations

import sys

import pytest

from mcp_server.doctor import SQLITE_CHECKS, _sqlite_vector_search
from tests_py._sqlite_vec import require_sqlite_vec


@pytest.fixture
def sqlite_fallback_path(tmp_path, monkeypatch):
    """Point the SQLite fallback DB at a temp file for one check call."""
    from mcp_server.infrastructure import memory_config

    monkeypatch.setenv(
        "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
    )
    memory_config.get_memory_settings.cache_clear()
    yield
    memory_config.get_memory_settings.cache_clear()


def test_is_required_and_in_sqlite_checks(sqlite_fallback_path):
    assert _sqlite_vector_search in SQLITE_CHECKS
    assert _sqlite_vector_search().optional is False


def test_names_missing_package_distinctly(sqlite_fallback_path, monkeypatch):
    """Package absent vs. load failure need opposite remedies."""
    monkeypatch.setitem(sys.modules, "sqlite_vec", None)  # force ImportError
    check = _sqlite_vector_search()
    assert check.ok is False
    assert "not installed" in check.detail
    assert "launcher" in check.fix or "install-deps" in check.fix


def test_loaded_reports_ok(sqlite_fallback_path):
    require_sqlite_vec()
    check = _sqlite_vector_search()
    assert check.ok is True
    assert "loaded" in check.detail


def test_names_missing_extension_api(sqlite_fallback_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "sqlite_vec", SimpleNamespace())
    monkeypatch.setattr(sqlite3, "Connection", object)
    check = _sqlite_vector_search()
    assert check.ok is False
    assert check.optional is False
    assert "enable_load_extension" in check.detail
    assert "Homebrew" in check.fix
    assert "uv-managed" in check.fix
    assert "python.org" not in check.fix
