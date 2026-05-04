"""Verify ``cortex_recall`` invokes the production handler exactly once
with arguments that are a subset of the production schema.

This is NOT a live PG test. We monkeypatch the imported ``handler`` symbol
inside ``cortex_caller`` and assert the call shape. The anti-cheating audit
test (``tests_py/handlers/test_beam_anticheat.py``) covers the static AST
invariants; this test covers the dynamic call invariant.
"""

from __future__ import annotations

import pytest

from benchmarks.llm_head_to_head import cortex_caller
from mcp_server.handlers import recall as production_recall


@pytest.fixture
def fake_handler(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace cortex_caller's bound ``handler`` with a recording stub.

    Returns a dict that gets populated with ``{'calls': [...], 'response': ...}``
    so the test can assert on call args.
    """
    state: dict = {"calls": [], "response": {"results": [], "total": 0}}

    async def fake(args: dict | None = None) -> dict:
        state["calls"].append(args)
        return state["response"]

    monkeypatch.setattr(cortex_caller, "handler", fake)
    return state


def test_cortex_recall_calls_production_handler_once(fake_handler) -> None:
    fake_handler["response"] = {
        "results": [
            {"id": "m-1", "content": "hello", "score": 0.9},
            {"id": "m-2", "content": "world", "score": 0.5},
        ],
        "total": 2,
    }
    out = cortex_caller.cortex_recall("why did we choose pgvector?", domain="beam")
    assert len(fake_handler["calls"]) == 1
    args = fake_handler["calls"][0]
    assert args["query"] == "why did we choose pgvector?"
    assert args["domain"] == "beam"
    assert args["max_results"] == cortex_caller.CORTEX_MAX_RESULTS

    # Subset-of-schema invariant (also enforced statically by anti-cheat).
    declared = set(production_recall.schema["inputSchema"]["properties"].keys())
    assert set(args.keys()).issubset(declared), (
        f"cortex_recall passed off-schema kwargs: {set(args.keys()) - declared}"
    )

    # Returns the response's ``results`` list verbatim (no post-processing).
    assert out == fake_handler["response"]["results"]


def test_cortex_recall_empty_question_returns_empty(fake_handler) -> None:
    assert cortex_caller.cortex_recall("") == []
    assert cortex_caller.cortex_recall("   ") == []
    # Critically: no handler invocation for empty input.
    assert fake_handler["calls"] == []


def test_cortex_recall_handles_non_dict_response(fake_handler) -> None:
    """Defensive: if production handler returned None (degraded), don't crash."""
    fake_handler["response"] = None  # type: ignore[assignment]
    assert cortex_caller.cortex_recall("q") == []


def test_cortex_recall_handles_missing_results_key(fake_handler) -> None:
    fake_handler["response"] = {"total": 0}  # no 'results' key
    assert cortex_caller.cortex_recall("q") == []
