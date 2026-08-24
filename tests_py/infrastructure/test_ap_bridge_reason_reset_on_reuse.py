"""Regression test (PR #449 review round 3): ``APBridge._unavailable_reason``
must not leak a stale reason from an earlier failed call into a later
successful one on the same, reused instance.

Bug: the reason was only cleared in ``connect()``'s slow (reconnect) path;
``connect()``'s fast path (already-connected client) skipped the clear, and
``call()``'s success branch never reset it either. A caller that reuses one
``WorkflowGraphASTSource``/``APBridge`` across a loop (the codebase already
does this — ``wiki_verify.py`` reuses one source across its candidate loop)
would see ``last_search_degraded_reason`` report a call as failed when it
had actually just succeeded, contradicting its own docstring ("None if it
succeeded").

Fix: ``call()`` resets ``self._unavailable_reason = None`` at its top (after
the allowlist check, before touching ``connect()``/the RPC), so each call's
own outcome is authoritative regardless of prior calls on the same instance.
"""

from __future__ import annotations

import asyncio

from mcp_server.infrastructure.ap_bridge import APBridge


class _HangingClient:
    """Never completes on its own — only a ceiling can terminate the call."""

    connected = True

    async def call(self, name, args):  # noqa: ANN001 — test double
        await asyncio.Event().wait()


class _OkClient:
    """Always succeeds."""

    connected = True

    async def call(self, name, args):  # noqa: ANN001 — test double
        return {"rows": [], "status": "ok"}


def test_second_successful_call_clears_a_prior_failure_reason() -> None:
    bridge = APBridge()
    bridge._client = _HangingClient()
    bridge._connected = True

    async def run():
        first = await bridge.call("search_codebase", {"query": "x"}, timeout_s=0.05)
        assert first is None
        assert bridge.unavailable_reason is not None  # first call genuinely failed

        # Same instance, reused (matches wiki_verify.py's loop pattern) — swap
        # in a client that succeeds and call again, with NO explicit clear.
        bridge._client = _OkClient()
        return await bridge.call("search_codebase", {"query": "y"}, timeout_s=5.0)

    second = asyncio.run(run())
    assert second == {"rows": [], "status": "ok"}
    # The stale reason from the FIRST call must not survive into the SECOND,
    # successful one.
    assert bridge.unavailable_reason is None
