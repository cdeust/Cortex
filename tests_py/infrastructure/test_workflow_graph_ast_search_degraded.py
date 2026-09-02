"""Tests for ``WorkflowGraphASTSource.last_search_degraded_reason``.

Bug (PR #449 review): ``unified_search`` derived ``status`` from the static
``is_enabled()`` config flag only. An AP that is enabled but wedged/timed
out on a ``search_codebase`` call returned ``[]`` — byte-for-byte
indistinguishable, at the handler, from "AP genuinely found nothing".

Fix: the AST-source layer exposes ``last_search_degraded_reason``, reading
the same ``APBridge._unavailable_reason`` the bridge's own timeout/exception
handling already records (see ``ap_bridge.py::APBridge._degrade``) — no
second round-trip, no widened return type.

Uses a real ``APBridge`` wired to a hanging fake client (never completes on
its own — ``asyncio.Event().wait()``) so the interactive ceiling is what
terminates the call, matching the model in
``test_ap_bridge_interactive_timeout.py``.
"""

from __future__ import annotations

import asyncio

from mcp_server.infrastructure import workflow_graph_source_ast as mod
from mcp_server.infrastructure.ap_bridge import APBridge
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
)


class _HangingClient:
    """Stands in for a connected-but-wedged AP: the call never completes
    on its own, so only the interactive ceiling can terminate it."""

    connected = True

    async def call(self, name, args):  # noqa: ANN001 — test double
        await asyncio.Event().wait()


def _wedged_bridge() -> APBridge:
    bridge = APBridge()
    bridge._client = _HangingClient()
    bridge._connected = True
    return bridge


def test_search_codebase_on_wedged_bridge_returns_empty_and_sets_reason(
    monkeypatch,
) -> None:
    # Tiny ceiling: the hanging client would otherwise block the test
    # forever. The ceiling firing is the behavior under test, not an
    # incidental wall-clock assertion — same model as
    # test_ap_bridge_interactive_timeout.py.
    monkeypatch.setenv("CORTEX_AP_INTERACTIVE_TIMEOUT_S", "0.05")
    monkeypatch.setattr(mod, "is_enabled", lambda: True)
    monkeypatch.setattr(mod, "resolve_graph_path", lambda: "/fake/graph.kuzu")

    source = WorkflowGraphASTSource(bridge=_wedged_bridge())
    try:
        # Before any call: never attempted, so no degrade to report.
        assert source.last_search_degraded_reason is None

        hits = source.search_codebase("query", limit=5)

        # The silent-data-loss bug: hits alone cannot distinguish "AP
        # found nothing" from "AP call failed" — this is why the caller
        # (unified_search) must additionally check the reason below.
        assert hits == []
        reason = source.last_search_degraded_reason
        assert reason is not None
        assert "TimeoutError" in reason
        assert "search_codebase" in reason
    finally:
        source.close()


def test_search_codebase_disabled_leaves_reason_none(monkeypatch) -> None:
    # AP disabled: search_codebase short-circuits before ever touching the
    # bridge. This is the legitimate "AP not in play" contract, not a call
    # failure — last_search_degraded_reason must stay None.
    monkeypatch.setattr(mod, "is_enabled", lambda: False)

    source = WorkflowGraphASTSource(bridge=_wedged_bridge())
    try:
        assert source.search_codebase("query", limit=5) == []
        assert source.last_search_degraded_reason is None
    finally:
        source.close()
