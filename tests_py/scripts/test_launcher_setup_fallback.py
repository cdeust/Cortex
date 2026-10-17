"""Setup records why an eligible store stays on SQLite (ADR-1110, owner D3).

PR #748's round-3 review, N1: the fallback cause was only in ``setup.log``;
the outcome said ``ready`` and nothing reached the user. Now the outcome
carries ``sqlite_fallback`` and the SessionStart launch hands it to the hook.

source: ADR-1110
"""

from __future__ import annotations

import os

from tests_py.scripts import test_launcher_setup as _base

setup_env = _base.setup_env  # the fixture, shared
_warm = _base._warm


_CAUSE = "managed PostgreSQL did not start: ServerError: dyld"  # source: test value


def test_an_eligible_store_left_on_sqlite_records_why(setup_env, monkeypatch, capsys):
    # D3 (round-3 N1): the fallback was only in setup.log; the outcome said "ready".
    setup, _deps_mod, deps, _installed, _removed = setup_env
    import launcher_pg_provision

    monkeypatch.setattr(
        setup,
        "managed_pg_step",
        lambda d, say: launcher_pg_provision.StepOutcome(fallback=_CAUSE),
    )
    _warm(monkeypatch, setup)
    assert setup.run(deps, "launcher.py") == 0
    assert setup.outcome(deps) == {
        "status": "ready",
        "error": "",
        "sqlite_fallback": _CAUSE,
    }
    assert setup.sqlite_fallback(deps) == _CAUSE
    assert f"[cortex-setup] SQLite fallback: {_CAUSE}" in capsys.readouterr().out


def test_a_later_failure_keeps_the_fallback_cause(setup_env, monkeypatch):
    setup, _deps_mod, deps, _installed, _removed = setup_env
    import launcher_pg_provision

    monkeypatch.setattr(
        setup,
        "managed_pg_step",
        lambda d, say: launcher_pg_provision.StepOutcome(fallback=_CAUSE),
    )
    _warm(monkeypatch, setup, cause="offline")
    assert setup.run(deps, "launcher.py") == 1
    assert setup.sqlite_fallback(deps) == _CAUSE


def test_the_session_start_launch_hands_the_fallback_to_the_hook(
    setup_env, monkeypatch
):
    setup, _deps_mod, deps, _installed, _removed = setup_env
    import launcher

    setup._record(deps, "ready", fallback=_CAUSE)
    monkeypatch.setattr(launcher.launcher_base_job, "require_ready", lambda *a: None)
    monkeypatch.setattr(launcher.launcher_site, "isolate_deps", lambda d: None)
    monkeypatch.setattr(
        launcher.launcher_ml, "start", lambda d, launcher_path: ("ready", "")
    )
    # _ensure_runtime writes os.environ itself: setenv first records the
    # original state, so teardown restores it and nothing leaks into the
    # hook tests that run later in this process.
    for name in (
        "CORTEX_SQLITE_FALLBACK",
        "CORTEX_SEMANTIC_SEARCH",
        "CORTEX_SEMANTIC_SEARCH_DETAIL",
    ):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    launcher._ensure_runtime("mcp_server.hooks.session_start", False, deps)
    assert "CORTEX_SQLITE_FALLBACK" not in os.environ  # not SQLite
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    launcher._ensure_runtime("mcp_server.hooks.session_start", False, deps)
    assert os.environ["CORTEX_SQLITE_FALLBACK"] == _CAUSE
