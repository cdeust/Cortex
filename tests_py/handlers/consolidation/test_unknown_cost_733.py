"""An unreported provider cost stays unknown, never a free 0.0 (#733, slice 2).

Before this change ``_parse_invoke_response`` returned ``cost_usd=0.0`` when
the CLI exited non-zero, printed nothing, printed non-JSON or omitted
``total_cost_usd``, so a cycle whose calls reported no cost read as a free
cycle (probe: ``docs/audits/operation-consumption-inventory-2026-11-05.md``).
No real ``claude`` subprocess is started here.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import mcp_server.handlers.consolidation.distill_drain as dd
import mcp_server.handlers.consolidation.headless_authoring as ha
from mcp_server.handlers.consolidation.claude_invoke import _parse_invoke_response


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (1, b""),
        (0, b""),
        (0, b"not json"),
        (0, b'{"result": "x"}'),
        (0, b'{"result": "x", "total_cost_usd": null}'),
    ],
)
def test_unreported_cost_is_none(returncode: int, stdout: bytes) -> None:
    ir = _parse_invoke_response(returncode, stdout, b"", ha)
    assert ir.cost_usd is None


def test_reported_zero_cost_stays_zero() -> None:
    ir = _parse_invoke_response(0, b'{"result": "x", "total_cost_usd": 0.0}', b"", ha)
    assert ir.cost_usd == 0.0
    assert ir.text == "x"


def test_reported_cost_is_read() -> None:
    raw = b'{"result": "x", "total_cost_usd": 0.0123}'
    assert _parse_invoke_response(0, raw, b"", ha).cost_usd == pytest.approx(0.0123)


def test_unpriced_charge_is_counted_not_summed() -> None:
    budget = ha.CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=1.0)
    ha.cycle_budget_charge(budget, None)
    ha.cycle_budget_charge(budget, 0.25)
    ha.cycle_budget_charge(budget, None)
    assert budget.usd_spent == pytest.approx(0.25)
    assert budget.unpriced_calls == 2
    assert not ha.cycle_budget_exhausted(budget)


def test_distill_summary_reports_unpriced_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ha, "CORTEX_HEADLESS_AGENTS", 1)

    async def invoke(prompt: str, **_: Any) -> ha.InvokeResult:
        return ha.InvokeResult(text="ok", cost_usd=None)

    jobs = [{"marker": f"m{i}", "dossier_kind": "k", "prompt": "p"} for i in range(3)]
    summary = asyncio.run(dd.run_distill_drain_cycle(jobs, invoke=invoke))
    assert summary.unpriced_calls == 3
    assert summary.usd_spent == 0.0
    assert all(r.cost_usd is None for r in summary.results)
