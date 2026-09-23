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
import subprocess
import sys
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

    # Dotted to match the path-derived name mutmut keys mutant trampolines
    # on ("scripts.setup.*") — a synthetic name makes every mutant look
    # unreached to a scoped mutation run (issue #262).
    spec = importlib.util.spec_from_file_location("scripts.setup", SETUP_MODULE_PATH)
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
def test_main_model_download_is_lazy_in_sqlite_mode(monkeypatch, skip_postgres):
    """SQLite mode (the plugin's zero-config default) must NOT pre-cache
    the embedding model at install time — it downloads lazily on first
    encode (embedding_engine._ensure_model). The PostgreSQL opt-in path
    keeps the eager pre-cache. Source: sqlite-first install change."""
    mod = _load_setup_module(monkeypatch, "sqlite" if skip_postgres else None)

    for name in (
        "check_python",
        "check_postgresql",
        "install_deps",
        "setup_database",
        "verify",
    ):
        monkeypatch.setattr(mod, name, mock.Mock())
    cache_model = mock.Mock()
    monkeypatch.setattr(mod, "cache_embedding_model", cache_model)

    mod.main()

    if skip_postgres:
        cache_model.assert_not_called()
        mod.setup_database.assert_not_called()
        mod.check_postgresql.assert_not_called()
    else:
        cache_model.assert_called_once()
        mod.setup_database.assert_called_once()
        mod.check_postgresql.assert_called_once()


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


def test_model_checks_reports_failure_for_non_import_error(monkeypatch):
    """A torch/torchaudio ABI mismatch (issue #621) raises OSError deep
    inside the sentence_transformers import chain, not ImportError. Before
    issue #633's fix, that exception escaped _model_checks() uncaught and
    crashed scripts/setup.py before it could print a "[FAIL]" line for
    run_setup_py to name — reproducing exactly the confusing message the
    reporter saw."""
    mod = _load_setup_module(monkeypatch, None)

    real_import = __import__

    def _boom(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise OSError("Could not load this library: libtorchaudio.pyd")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _boom)

    checks = mod._model_checks()

    assert ("sentence-transformers", False) in checks


def test_model_cache_child_source_compiles(monkeypatch, tmp_path):
    mod = _load_setup_module(monkeypatch, None)

    src = mod._model_cache_child_source(mod.SCRIPT_DIR, str(tmp_path / "deps"))

    compile(src, "<model-cache-child>", "exec")


def test_model_cache_child_source_runs_end_to_end_against_a_stub(monkeypatch, tmp_path):
    """The seam issue #633 introduces is otherwise only ever exercised as
    an opaque string mocked out by every test that touches
    cache_embedding_model() -- this actually runs the generated child
    process, proving the isolate_deps bootstrap and the import chain both
    work, not just that the source happens to parse."""
    mod = _load_setup_module(monkeypatch, None)

    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "sentence_transformers.py").write_text(
        "class SentenceTransformer:\n"
        "    def __init__(self, *a, **k):\n"
        "        pass\n"
        "\n"
        "    def encode(self, texts):\n"
        "        class _Shape:\n"
        "            shape = (len(texts), 384)\n"
        "        return _Shape()\n"
    )
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()

    src = mod._model_cache_child_source(mod.SCRIPT_DIR, str(deps_dir))
    result = subprocess.run(
        [sys.executable, "-c", src],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "PYTHONPATH": str(shadow_dir),
        },
        timeout=30,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Model loaded: 384D" in result.stdout


def test_model_cache_child_source_escapes_special_characters_in_paths(monkeypatch):
    """repr() rather than an f-string is what the function's own docstring
    claims keeps a path containing a backslash or apostrophe -- the exact
    shape of a Windows path under a name with an apostrophe -- from
    corrupting the child's source (issue #633)."""
    mod = _load_setup_module(monkeypatch, None)

    tricky_deps = r"C:\Users\O'Brien\.claude\plugins\deps"
    tricky_script_dir = Path(r"C:\Users\O'Brien\Cortex\scripts")

    src = mod._model_cache_child_source(tricky_script_dir, tricky_deps)

    compile(src, "<model-cache-child>", "exec")
    import ast

    literals = [
        node.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert str(tricky_script_dir) in literals
    assert tricky_deps in literals
