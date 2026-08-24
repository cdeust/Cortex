"""Tests for ``unified_search.handler``'s degraded-status signal (PR #449).

Bug: ``status`` was derived from the static ``is_enabled()`` config flag
only. An AP that is enabled but times out/errors on the actual
``search_codebase`` call returned ``[]`` for ``ap_hits`` — the response was
``status="ok", sources=["cortex","ap"], counts.ap=0``, indistinguishable
from AP genuinely finding nothing (silent data loss the PR's own body
claims to have fixed for the *timeout* path but the *response* never
surfaced).

Fix: the handler reads ``WorkflowGraphASTSource.last_search_degraded_reason``
after the call and sets ``status="partial"`` + a ``degraded`` field naming
the source and reason whenever AP was attempted but failed.
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers import unified_search


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _fake_recall_empty(_args: dict) -> dict:
    return {"memories": []}


class _WedgedASTSource:
    """Stands in for a AST source whose bridge just timed out: no hits,
    but a recorded degrade reason — the exact silent-data-loss shape."""

    def __init__(self) -> None:
        self.last_search_degraded_reason: str | None = None

    def search_codebase(self, query: str, *, limit: int = 20) -> list[dict]:
        self.last_search_degraded_reason = (
            "TimeoutError: AP call search_codebase exceeded 30s"
        )
        return []


class _HealthyASTSource:
    """AP genuinely ran and found nothing — the case that must stay
    status=ok, degraded=None (never conflated with a call failure)."""

    def __init__(self) -> None:
        self.last_search_degraded_reason: str | None = None

    def search_codebase(self, query: str, *, limit: int = 20) -> list[dict]:
        return []


def test_wedged_ap_call_surfaces_partial_status_and_degraded_reason(
    monkeypatch,
) -> None:
    monkeypatch.setattr(unified_search, "recall_handler", _fake_recall_empty)
    monkeypatch.setattr(unified_search, "is_enabled", lambda: True)
    monkeypatch.setattr(unified_search, "WorkflowGraphASTSource", _WedgedASTSource)

    resp = _run(unified_search.handler({"query": "anything"}))

    # This is the assertion that fails on the pre-fix handler: status="ok"
    # and degraded absent/None even though AP never actually returned.
    assert resp["status"] == "partial"
    assert resp["degraded"] is not None
    assert resp["degraded"]["source"] == "ap"
    assert "TimeoutError" in resp["degraded"]["reason"]
    assert resp["counts"]["ap"] == 0
    assert resp["sources"] == ["cortex", "ap"]


def test_ap_genuinely_empty_stays_ok_with_no_degraded_flag(monkeypatch) -> None:
    monkeypatch.setattr(unified_search, "recall_handler", _fake_recall_empty)
    monkeypatch.setattr(unified_search, "is_enabled", lambda: True)
    monkeypatch.setattr(unified_search, "WorkflowGraphASTSource", _HealthyASTSource)

    resp = _run(unified_search.handler({"query": "anything"}))

    assert resp["status"] == "ok"
    assert resp["degraded"] is None
    assert resp["counts"]["ap"] == 0


def test_ap_disabled_stays_partial_with_no_degraded_flag(monkeypatch) -> None:
    monkeypatch.setattr(unified_search, "recall_handler", _fake_recall_empty)
    monkeypatch.setattr(unified_search, "is_enabled", lambda: False)

    resp = _run(unified_search.handler({"query": "anything"}))

    assert resp["status"] == "partial"
    assert resp["degraded"] is None
    assert resp["sources"] == ["cortex"]
