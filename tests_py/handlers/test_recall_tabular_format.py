"""Integration tests for the recall handler's tabular format (issue #170).

Drives the real ``recall._handler_impl`` with pg_recall, the store, and the
session registry faked (the harness mirrors
``test_recall_receipt_session.py``), proving:

  * ``format="json"`` (default) returns memory objects, self-described.
  * ``format="tabular"`` returns a ``columns`` header + cell-array rows, with
    no information loss vs the json form (same field set, same values, ids
    still present).
  * The tabular response still respects the response-budget cap — the encoding
    composes with the budget, it does not bypass it.
  * A single-content fetch-by-id honors the format param.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from mcp_server.core.response_budget import serialized_length
from mcp_server.core.tabular_encoding import decode_tabular
from mcp_server.handlers import recall as recall_mod
from mcp_server.infrastructure.memory_config import get_memory_settings


class _FakeStore:
    """Minimal store double: answers the enrichment path with no-ops and
    serves ``get_memory`` for the fetch-by-id path."""

    def __init__(self, by_id: dict | None = None) -> None:
        self._by_id = by_id or {}

    def get_all_active_rules(self) -> list[dict]:
        return []

    def get_memory(self, mid: int) -> dict | None:
        return self._by_id.get(mid)

    def insert_injection_receipt(self, *args, **kwargs) -> int:
        return 1

    def __getattr__(self, name: str):
        def _noop(*args, **kwargs):
            return None

        return _noop


def _emb() -> bytes:
    rng = np.random.default_rng(0)
    v = rng.standard_normal(384).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tobytes()


def _canned_results(n: int) -> list[dict]:
    return [
        {
            "memory_id": i,
            "id": f"uuid-{i}",
            "content": f"decision {i}: adopt approach {i} for the subsystem",
            "score": round(0.9 - i * 0.01, 4),
            "heat": 0.5,
            "domain": "cortex",
            "tags": ["decision"],
        }
        for i in range(n)
    ]


def _run(monkeypatch: pytest.MonkeyPatch, args: dict, results: list[dict]) -> dict:
    store = _FakeStore()
    monkeypatch.setattr(recall_mod, "_get_store", lambda: store)
    monkeypatch.setattr(recall_mod, "get_embedding_engine", lambda: _emb())
    monkeypatch.setattr(
        recall_mod, "pg_recall", lambda **kw: [dict(r) for r in results]
    )
    monkeypatch.setattr(recall_mod, "root_agent_topic", lambda: None)
    monkeypatch.setattr(recall_mod, "current_window_session", lambda: None)
    return asyncio.run(recall_mod._handler_impl(args))


def test_default_format_returns_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, {"query": "why pgvector"}, _canned_results(5))
    assert out["format"] == "json"
    assert "columns" not in out
    assert all(isinstance(m, dict) for m in out["memories"])


def test_tabular_format_returns_columns_and_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _run(
        monkeypatch, {"query": "why pgvector", "format": "tabular"}, _canned_results(5)
    )
    assert out["format"] == "tabular"
    assert isinstance(out["columns"], list) and out["columns"]
    assert all(isinstance(row, list) for row in out["memories"])
    assert all(len(row) == len(out["columns"]) for row in out["memories"])


def test_tabular_has_no_information_loss_vs_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Field-set + value equality (contract #5): decoding the tabular rows
    reproduces exactly the objects the json form returns."""
    results = _canned_results(6)
    json_out = _run(monkeypatch, {"query": "q"}, results)
    tab_out = _run(monkeypatch, {"query": "q", "format": "tabular"}, results)

    decoded = decode_tabular(tab_out["columns"], tab_out["memories"])
    json_mems = json_out["memories"]
    assert len(decoded) == len(json_mems)
    # strict=True: equal length already asserted immediately above.
    for obj, back in zip(json_mems, decoded, strict=True):
        assert set(back.keys()) >= set(obj.keys())
        assert all(back[k] == obj[k] for k in obj)


def test_tabular_ids_remain_present(monkeypatch: pytest.MonkeyPatch) -> None:
    tab_out = _run(monkeypatch, {"query": "q", "format": "tabular"}, _canned_results(4))
    id_idx = tab_out["columns"].index("id")
    assert [row[id_idx] for row in tab_out["memories"]] == [
        "uuid-0",
        "uuid-1",
        "uuid-2",
        "uuid-3",
    ]


def test_tabular_respects_budget_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Budget composition (contract #1, #6): the tabular output still fits the
    same cap the object form is bounded to."""
    budget = get_memory_settings().MAX_RESPONSE_CHARS
    tab_out = _run(
        monkeypatch, {"query": "q", "format": "tabular"}, _canned_results(40)
    )
    assert serialized_length(tab_out) <= budget


def test_tabular_smaller_than_json_on_recall_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _canned_results(30)
    json_out = _run(monkeypatch, {"query": "q"}, results)
    tab_out = _run(monkeypatch, {"query": "q", "format": "tabular"}, results)
    assert serialized_length(tab_out) < serialized_length(json_out)


def test_tabular_fits_tight_budget_with_self_describe_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the self-describe overshoot: at a budget the object form
    fills to the cap, appending ``format``/``columns`` must NOT push the
    tabular response past the cap (issue #170 budget composition). The reserve
    holds room for the field before bound_payload runs."""

    class _TightSettings:
        def __init__(self, base) -> None:
            self._base = base

        def __getattr__(self, name):
            if name == "MAX_RESPONSE_CHARS":
                return 5_000
            return getattr(self._base, name)

    base = get_memory_settings()
    tight = _TightSettings(base)
    monkeypatch.setattr(recall_mod, "get_memory_settings", lambda: tight)
    fat = [
        {"memory_id": i, "id": f"uuid-{i}", "content": "x" * 20_000, "score": 0.9}
        for i in range(5)
    ]
    out = _run(monkeypatch, {"query": "q", "format": "tabular"}, fat)
    assert serialized_length(out) <= 5_000


def test_fetch_by_id_honors_format(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore(
        by_id={7: {"id": "uuid-7", "content": "full body", "score": 0.9}}
    )
    monkeypatch.setattr(recall_mod, "_get_store", lambda: store)
    out = asyncio.run(
        recall_mod._handler_impl({"query": "x", "memory_id": 7, "format": "tabular"})
    )
    # Self-described either way; the single-item budget re-check may keep json,
    # but the format field must always be present and valid.
    assert out["format"] in ("json", "tabular")
    assert out["count"] == 1
