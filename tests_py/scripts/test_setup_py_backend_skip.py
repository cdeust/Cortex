"""Tests for scripts/setup.py CI/testing sqlite-skip mode — issue #113.

Source: issue #113 — the Windows postInstall path (plugin.json ->
install-plugin.sh -> scripts/setup.py on Windows) had zero CI coverage,
which is how the "Unsupported OS" regression on native Windows shipped
undetected. ``CORTEX_MEMORY_STORE_BACKEND=sqlite`` lets CI exercise
scripts/setup.py's OS-dispatch-reachable steps (dependency install,
embedding-model caching, verification) on a runner with no PostgreSQL
server provisioned, without inventing a second unverified dispatch path.

These tests exercise the pure module-level flag derivation and the
branching it drives in ``verify()``; they do not run pip installs or a
real PostgreSQL connection (that end-to-end proof is the CI job itself —
see .github/workflows/ci.yml test-windows).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_MODULE_PATH = REPO_ROOT / "scripts" / "setup.py"


def _load_setup_module(monkeypatch, store_backend: str | None):
    """Import scripts/setup.py fresh with a given CORTEX_MEMORY_STORE_BACKEND.

    Pre:  store_backend is None (unset) or a string.
    Post: returns a freshly executed module object; SKIP_POSTGRES reflects
          the env var as read at that module's import time.
    """
    if store_backend is None:
        monkeypatch.delenv("CORTEX_MEMORY_STORE_BACKEND", raising=False)
    else:
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", store_backend)

    spec = importlib.util.spec_from_file_location(
        "_cortex_setup_script", SETUP_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "store_backend,expected",
    [
        (None, False),
        ("", False),
        ("postgresql", False),
        ("auto", False),
        ("sqlite", True),
        ("SQLite", True),  # case-insensitive
        (" sqlite ", True),  # whitespace-tolerant
    ],
)
def test_skip_postgres_flag_derivation(monkeypatch, store_backend, expected):
    mod = _load_setup_module(monkeypatch, store_backend)
    assert mod.SKIP_POSTGRES is expected


def test_verify_selects_sqlite_checks_when_skip_postgres(monkeypatch):
    """verify() branch selection, hermetic (issue #113 CI run 29360566538).

    The prior version of this test asserted a real SystemExit from
    verify(), which depends on whether sentence-transformers/flashrank/
    psycopg happen to be importable and whether a PostgreSQL server is
    reachable in whatever environment runs the suite — non-deterministic
    across CI jobs/matrix entries, exactly the flakiness this policy
    forbids. _sqlite_checks/_postgres_checks/_model_checks are documented
    as "never raises" (see their docstrings), so the only thing verify()
    itself is responsible for is: which of _sqlite_checks/_postgres_checks
    it calls, and whether it exits when a returned check is False. Both
    are testable by mocking the helpers directly — no import availability,
    no network, no real database needed.
    """
    mod = _load_setup_module(monkeypatch, "sqlite")

    sqlite_checks = mock.Mock(return_value=[("sqlite3 stdlib", True)])
    postgres_checks = mock.Mock(return_value=[("PostgreSQL connection", True)])
    model_checks = mock.Mock(
        return_value=[("sentence-transformers", True), ("FlashRank reranker", True)]
    )
    monkeypatch.setattr(mod, "_sqlite_checks", sqlite_checks)
    monkeypatch.setattr(mod, "_postgres_checks", postgres_checks)
    monkeypatch.setattr(mod, "_model_checks", model_checks)

    mod.verify()  # all mocked checks pass -> must not exit

    sqlite_checks.assert_called_once()
    postgres_checks.assert_not_called()
    model_checks.assert_called_once()


def test_verify_selects_postgres_checks_when_not_skip_postgres(monkeypatch):
    mod = _load_setup_module(monkeypatch, None)

    sqlite_checks = mock.Mock(return_value=[("sqlite3 stdlib", True)])
    postgres_checks = mock.Mock(return_value=[("PostgreSQL connection", True)])
    model_checks = mock.Mock(
        return_value=[("sentence-transformers", True), ("FlashRank reranker", True)]
    )
    monkeypatch.setattr(mod, "_sqlite_checks", sqlite_checks)
    monkeypatch.setattr(mod, "_postgres_checks", postgres_checks)
    monkeypatch.setattr(mod, "_model_checks", model_checks)

    mod.verify()  # all mocked checks pass -> must not exit

    postgres_checks.assert_called_once()
    sqlite_checks.assert_not_called()
    model_checks.assert_called_once()


@pytest.mark.parametrize("skip_postgres", [True, False])
def test_verify_exits_when_any_mocked_check_fails(monkeypatch, skip_postgres):
    mod = _load_setup_module(monkeypatch, "sqlite" if skip_postgres else None)

    monkeypatch.setattr(
        mod, "_sqlite_checks", mock.Mock(return_value=[("sqlite3 stdlib", True)])
    )
    monkeypatch.setattr(
        mod,
        "_postgres_checks",
        mock.Mock(return_value=[("PostgreSQL connection", False)]),
    )
    monkeypatch.setattr(
        mod,
        "_model_checks",
        mock.Mock(return_value=[("sentence-transformers", False)]),
    )

    with pytest.raises(SystemExit):
        mod.verify()
