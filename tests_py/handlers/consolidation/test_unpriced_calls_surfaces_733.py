"""Where an unpriced call is reported, and when a dead call costs nothing (#733).

Slice 2 of #733 counts the calls whose cost the CLI did not report
(``CycleBudget.unpriced_calls``). This file pins the three places that count
must reach or be decided: ``_claude_invoke``'s two early returns (no child
started is a known 0.0, a killed child is unknown), the cycle roll-up
``_summarize_cycle``, and the ``headless_authoring`` stanza of
``run_wiki_maintenance``. Each module is imported by its own dotted path so
the mutation gate (``scripts/ci_mutation_diff.py`` ``select_tests``) runs
these tests against it. No real ``claude`` subprocess is started.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import mcp_server.handlers.consolidation.claude_invoke as ci
import mcp_server.handlers.consolidation.cycle_orchestration as co
import mcp_server.handlers.consolidation.headless_authoring as ha
from mcp_server.handlers.consolidation import wiki_maintenance
from mcp_server.handlers.consolidation.cycle_types import CycleBudget, CycleSummary
from tests_py.handlers.consolidation.test_wiki_maintenance import (
    _FakeSqliteStore,
    _silence_everything_except_citation_seed,
)


class _ExitedProc:
    returncode = 0


def _invoke_with(monkeypatch, spawned: Any, comm: Any) -> Any:
    async def _spawn(argv, cwd, child_env):
        return spawned

    async def _communicate(proc, prompt, call_timeout):
        return comm

    monkeypatch.setattr(ci, "_spawn_claude_process", _spawn)
    monkeypatch.setattr(ci, "_communicate_with_timeout", _communicate)
    return asyncio.run(ci._claude_invoke("p", timeout=1.0))


def test_no_child_started_is_a_known_zero_cost(monkeypatch) -> None:
    ir = _invoke_with(monkeypatch, spawned=None, comm=None)
    assert ir.text is None
    assert ir.cost_usd == 0.0
    assert ir.cost_usd is not None


def test_a_child_with_no_response_has_an_unknown_cost(monkeypatch) -> None:
    ir = _invoke_with(monkeypatch, spawned=_ExitedProc(), comm=None)
    assert ir.text is None
    assert ir.cost_usd is None


def test_a_response_is_parsed_with_its_reported_cost(monkeypatch) -> None:
    out = b'{"result": "x", "total_cost_usd": 0.5}'
    ir = _invoke_with(monkeypatch, spawned=_ExitedProc(), comm=(out, b""))
    assert ir.text == "x"
    assert ir.cost_usd == 0.5


def test_cycle_summary_carries_the_unpriced_count() -> None:
    budget = CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=0.0)
    budget.usd_spent = 0.25
    budget.unpriced_calls = 3
    summary = co._summarize_cycle(time.monotonic(), [], [], [], [], budget, ha)
    assert summary.unpriced_calls == 3
    assert summary.usd_spent == 0.25


def test_wiki_maintenance_reports_unpriced_calls(monkeypatch) -> None:
    _silence_everything_except_citation_seed(monkeypatch)

    async def _cycle() -> CycleSummary:
        return CycleSummary(
            pages_scanned=0,
            pages_with_gaps=0,
            drains_attempted=2,
            drains_filled=2,
            drains_failed=0,
            duration_ms=0,
            results=[],
            unpriced_calls=2,
        )

    monkeypatch.setattr(wiki_maintenance, "_headless_authoring_enabled", lambda: True)
    monkeypatch.setattr(wiki_maintenance, "run_headless_authoring_cycle", _cycle)
    result = asyncio.run(
        wiki_maintenance.run_wiki_maintenance(
            _FakeSqliteStore(), max_purges_per_axis=None
        )
    )
    assert result["headless_authoring"]["unpriced_calls"] == 2
