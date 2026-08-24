"""Tests for the interactive read-path timeout on ``APBridge.call``.

Bug: the AP client runs with ``callTimeoutMs=0`` (indexing may legitimately
exceed any fixed bound), so a connected-but-wedged AP had only the 600s
wedge-silence window as a backstop. Interactive read-path calls
(search_codebase, get_symbol, …) inherited that 600s, so unified_search
would hang for up to 10 minutes instead of degrading to Cortex-only.
(get_causal_chain has no AP dependency and is unaffected.)

Fix: ``call(tool, args, timeout_s=...)`` wraps the client call in
``asyncio.wait_for`` and degrades a timeout to ``None`` (→ Cortex-only). The
interactive wrappers pass ``interactive_call_timeout_s()``; indexing wrappers
stay unbounded. These tests use a fake client so no subprocess is spawned.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.infrastructure.ap_bridge import APBridge
from mcp_server.infrastructure.mcp_call_timeout import interactive_call_timeout_s


class _HangingClient:
    """Stands in for a connected AP whose call never returns."""

    connected = True

    async def call(self, name, args):  # noqa: ANN001 — test double
        await asyncio.Event().wait()  # blocks forever


class _SlowClient:
    """Returns after ``delay`` seconds — used to prove the ceiling fires
    below the delay and passes above it."""

    connected = True

    def __init__(self, delay: float, payload) -> None:
        self._delay = delay
        self._payload = payload

    async def call(self, name, args):  # noqa: ANN001 — test double
        await asyncio.sleep(self._delay)
        return self._payload


def _bridge_with(client) -> APBridge:
    bridge = APBridge()
    bridge._client = client
    bridge._connected = True
    return bridge


def test_interactive_timeout_degrades_to_none() -> None:
    bridge = _bridge_with(_HangingClient())

    async def run():
        # A tiny explicit ceiling: the hanging client would otherwise block
        # forever; the bridge must return None well within the test.
        return await bridge.call("search_codebase", {"query": "x"}, timeout_s=0.05)

    result = asyncio.run(run())
    assert result is None
    assert "TimeoutError" in (bridge._unavailable_reason or "")
    assert "search_codebase" in (bridge._unavailable_reason or "")


def test_call_under_ceiling_returns_payload() -> None:
    bridge = _bridge_with(_SlowClient(delay=0.0, payload={"rows": [], "status": "ok"}))

    async def run():
        return await bridge.call("get_symbol", {"qualified_name": "f"}, timeout_s=5.0)

    assert asyncio.run(run()) == {"rows": [], "status": "ok"}


def test_no_timeout_argument_is_unbounded() -> None:
    # Indexing wrappers pass no timeout_s; the call must NOT be wrapped in
    # wait_for. A client that returns promptly proves the unbounded path
    # still returns its payload (regression guard on the None-branch).
    bridge = _bridge_with(_SlowClient(delay=0.0, payload={"ok": True}))

    async def run():
        return await bridge.call("index_codebase", {"path": "/x"})

    assert asyncio.run(run()) == {"ok": True}


def test_search_codebase_wrapper_passes_interactive_ceiling(monkeypatch) -> None:
    # The interactive wrapper must forward a positive, bounded timeout_s.
    captured: dict[str, float | None] = {}

    async def fake_call(self, tool, args=None, *, timeout_s=None):  # noqa: ANN001
        captured["tool"] = tool
        captured["timeout_s"] = timeout_s
        return {"rows": [], "status": "ok"}

    monkeypatch.setattr(APBridge, "call", fake_call)
    bridge = APBridge()

    asyncio.run(bridge.search_codebase("/graph", "query", limit=5))
    assert captured["tool"] == "search_codebase"
    assert captured["timeout_s"] == interactive_call_timeout_s()
    assert captured["timeout_s"] > 0


def test_index_codebase_wrapper_stays_unbounded(monkeypatch) -> None:
    # The indexing wrapper must NOT forward a timeout (unbounded ingest).
    captured: dict[str, float | None] = {}

    async def fake_call(self, tool, args=None, *, timeout_s=None):  # noqa: ANN001
        captured["tool"] = tool
        captured["timeout_s"] = timeout_s
        return {"graph_path": "/g"}

    monkeypatch.setattr(APBridge, "call", fake_call)
    bridge = APBridge()

    asyncio.run(bridge.index_codebase("/src", output_dir="/out"))
    assert captured["tool"] == "index_codebase"
    assert captured["timeout_s"] is None


def test_interactive_ceiling_default_is_bounded_and_env_overridable(
    monkeypatch,
) -> None:
    from mcp_server.infrastructure.mcp_call_timeout import default_call_timeout_s

    monkeypatch.delenv("CORTEX_AP_INTERACTIVE_TIMEOUT_S", raising=False)
    default = interactive_call_timeout_s()
    # Interactive ceiling must be positive and strictly below the 600s
    # indexing wedge-silence window — the whole point of the fix.
    assert 0 < default < default_call_timeout_s()

    monkeypatch.setenv("CORTEX_AP_INTERACTIVE_TIMEOUT_S", "12.5")
    assert interactive_call_timeout_s() == 12.5

    # Malformed / non-positive overrides fall back to the default, never
    # to an unbounded wait.
    monkeypatch.setenv("CORTEX_AP_INTERACTIVE_TIMEOUT_S", "0")
    assert interactive_call_timeout_s() == default
    monkeypatch.setenv("CORTEX_AP_INTERACTIVE_TIMEOUT_S", "not-a-number")
    assert interactive_call_timeout_s() == default


@pytest.mark.parametrize("tool", ["search_codebase", "get_symbol", "get_context"])
def test_named_interactive_tools_degrade_not_hang(tool: str) -> None:
    # Sanity: the bridge.call ceiling applies uniformly to the interactive
    # read tools by name.
    bridge = _bridge_with(_HangingClient())

    async def run():
        return await bridge.call(tool, {}, timeout_s=0.05)

    assert asyncio.run(run()) is None
