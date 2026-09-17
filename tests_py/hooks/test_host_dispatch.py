"""Unit tests for ``host_dispatch``'s per-event dispatch mechanics: the
``CLAUDE_PROJECT_ROOT`` precedence helper ``entry.main`` calls before its
dispatch loop.

These are unit-level (no subprocess) so the precedence logic is pinned
directly, per the reviewer's note on PR #608 that a subprocess round trip
through ``entry.py`` is not required to catch a precedence inversion here.
"""

from __future__ import annotations

import pytest

from mcp_server.hooks import host_dispatch
from mcp_server.hooks.host_dispatch import apply_project_root


def test_apply_project_root_fills_unset_value_from_event_cwd() -> None:
    environ: dict[str, str] = {}
    apply_project_root(environ, "/from/event")
    assert environ["CLAUDE_PROJECT_ROOT"] == "/from/event"


def test_apply_project_root_keeps_preset_value() -> None:
    environ = {"CLAUDE_PROJECT_ROOT": "/preset/elsewhere"}
    apply_project_root(environ, "/from/event")
    assert environ["CLAUDE_PROJECT_ROOT"] == "/preset/elsewhere"


def test_apply_project_root_no_op_on_falsy_cwd() -> None:
    environ: dict[str, str] = {}
    apply_project_root(environ, None)
    assert "CLAUDE_PROJECT_ROOT" not in environ
    apply_project_root(environ, "")
    assert "CLAUDE_PROJECT_ROOT" not in environ


def _fake_run_event(monkeypatch: pytest.MonkeyPatch, codes: list[int]) -> list[str]:
    """Patch ``run_event`` to consume ``codes`` in order without running a
    real module; returns the list of payloads it was actually called with."""
    calls: list[str] = []

    def fake(_module: str, payload: str) -> int:
        calls.append(payload)
        return codes[len(calls) - 1]

    monkeypatch.setattr(host_dispatch, "run_event", fake)
    return calls


def test_run_all_pretooluse_stops_on_first_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_run_event(monkeypatch, [2, 0])
    code = host_dispatch.run_all("mod", ["first", "second"], "PreToolUse")
    assert code == 2
    assert calls == ["first"]


def test_run_all_posttooluse_runs_all_and_takes_the_worst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_run_event(monkeypatch, [0, 2, 1])
    code = host_dispatch.run_all("mod", ["a", "b", "c"], "PostToolUse")
    assert code == 2
    assert calls == ["a", "b", "c"]
