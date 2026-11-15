"""The scripts apply the store's rule for which value names a database.

``scripts/setup_db.py`` dropped any value containing ``${`` and
``launcher_backend.map_database_option`` tested only ``.strip()``: a literal
``${`` in a password was replaced by the local default, and a ``DATABASE_URL``
left as ``${user_config.database_url}`` kept a real
``CLAUDE_PLUGIN_OPTION_DATABASE_URL`` from being mapped (notes 1 and 2 of the
review of #1051).

source: issue #704
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import launcher_backend  # noqa: E402
import setup_db  # noqa: E402

_LOCAL = "postgresql://127.0.0.1:5432/cortex"  # source: setup_db default
_REAL = "postgresql://u@db.invalid/cortex"
_PLACEHOLDER = "${user_config.database_url}"


@pytest.mark.parametrize("value", ["", "  ", _PLACEHOLDER])
def test_setup_db_reads_no_url_from_a_blank_or_unexpanded_value(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    assert setup_db._get_database_url() == _LOCAL


def test_setup_db_keeps_a_dollar_brace_inside_a_dsn(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", " postgresql://u:p${q}@h/db ")
    assert setup_db._get_database_url() == "postgresql://u:p${q}@h/db"


@pytest.mark.parametrize("database_url", ["", " ", _PLACEHOLDER])
def test_the_option_replaces_a_url_that_names_no_database(database_url):
    environ = {
        "DATABASE_URL": database_url,
        "CLAUDE_PLUGIN_OPTION_DATABASE_URL": f" {_REAL} ",
    }
    launcher_backend.map_database_option(environ)
    assert environ["DATABASE_URL"] == _REAL


def test_a_configured_url_wins_over_the_option():
    environ = {"DATABASE_URL": _REAL, "CLAUDE_PLUGIN_OPTION_DATABASE_URL": "x"}
    launcher_backend.map_database_option(environ)
    assert environ["DATABASE_URL"] == _REAL


@pytest.mark.parametrize("option", ["", " ", "${user_config.database_url}"])
def test_an_option_that_names_no_database_maps_nothing(option):
    environ = {"CLAUDE_PLUGIN_OPTION_DATABASE_URL": option}
    launcher_backend.map_database_option(environ)
    assert "DATABASE_URL" not in environ


def test_setup_db_run_directly_without_pythonpath_still_answers_in_json(tmp_path):
    # Codex review of #1052: run as `python scripts/setup_db.py` with no
    # PYTHONPATH, the shared import raised ModuleNotFoundError before any JSON.
    import json
    import os
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "setup_db.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = "postgresql://127.0.0.1:1/cortex_unreachable"
    done = subprocess.run(
        [sys.executable, "-I", str(script)],
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )  # fmt: skip
    assert "ModuleNotFoundError" not in done.stderr
    assert "status" in json.loads(done.stdout.strip().splitlines()[-1])
