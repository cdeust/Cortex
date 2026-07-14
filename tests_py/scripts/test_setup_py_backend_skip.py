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


def test_verify_skips_pg_checks_and_checks_sqlite3_when_skip_postgres(
    monkeypatch, capsys
):
    mod = _load_setup_module(monkeypatch, "sqlite")
    # sentence-transformers / flashrank are not installed in the test env,
    # so verify() would sys.exit(1) via fail(); that's expected here — we
    # only assert on what got printed, i.e. which checks it decided to run.
    with pytest.raises(SystemExit):
        mod.verify()
    out = capsys.readouterr().out
    assert "sqlite3 stdlib" in out
    assert "PostgreSQL connection" not in out
    assert "Extensions" not in out
    assert "PL/pgSQL" not in out


def test_verify_runs_pg_checks_when_not_skip_postgres(monkeypatch, capsys):
    mod = _load_setup_module(monkeypatch, None)
    with pytest.raises(SystemExit):
        mod.verify()
    out = capsys.readouterr().out
    assert "PostgreSQL connection" in out
    assert "sqlite3 stdlib" not in out
