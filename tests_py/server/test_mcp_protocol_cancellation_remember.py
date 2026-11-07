"""Issue #728 with a real mutating tool: ``remember`` cancelled mid-write.

``test_mcp_protocol_cancellation`` pins the protocol and admission boundary
with a synthetic handler and a plain SQLite file. Here the server is built by
the production registration (``tool_registry_memory.register``), the tool is
the real ``remember`` handler, and the store is the suite's isolated Cortex
SQLite store (``tests_py/conftest.py`` redirects ``CORTEX_MEMORY_DB_PATH``
to a throwaway tree before any import). The only test double is a gate on
the store instance's ``insert_memory_exact``: the handler has run its write
gate, embedding and curation, and blocks right before the row is written.

What both tests pin:
- the worker keeps the ``remember`` admission slot until it ends;
- ``abandoned_work`` counts it while it runs and records ``completed``;
- the memory row lands in the Cortex store after the client stopped
  listening, with the content that was sent, and nothing is written before.

``mode="legacy"`` puts the in-process server behind ``InMemoryTransport`` and
JSON-RPC, so the cancel crosses the transport as ``notifications/cancelled``
(or as the transport closing, for the disconnect test).

source: issue #728 (remaining slice 1: "the same scenario with a real mutating
tool (``remember``) on an isolated Cortex SQLite store")
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_memory
from mcp_server.handlers import abandoned_work
from mcp_server.handlers.admission import (
    _get_semaphore,
    current_budget,
    reset_semaphores,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.observability import metrics

_TOOL = "remember"
# source: deadlock guard, not a measurement — a wait that a correct
# implementation satisfies at once, bounded so a broken one fails the test.
# Larger than test_mcp_protocol_cancellation's 5 s: the real handler runs the
# write gate and the hash embedding before reaching the gate.
_GUARD = 30.0
# source: poll interval of the bounded waits, not a measurement.
_POLL = 0.001
_CONTENT = "Decision: issue 728 cancelled remember must still land its row."


@pytest.fixture(autouse=True)
def _clean_state():
    reset_semaphores()
    metrics.reset()
    abandoned_work.reset()
    yield
    reset_semaphores()
    metrics.reset()
    abandoned_work.reset()


class _GatedInsert:
    """Blocks the store's exact insert until released, then delegates."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self._real = store.insert_memory_exact
        self.reached = threading.Event()
        self.release = threading.Event()
        self.ids: list[int] = []

    def __call__(self, data: dict[str, Any]) -> tuple[int, bool]:
        self.reached.set()
        assert self.release.wait(_GUARD)
        mem_id, inserted = self._real(data)
        self.ids.append(mem_id)
        return mem_id, inserted

    def total(self) -> int:
        return self.store.count_memories().get("total", 0)


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> _GatedInsert:
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    gated = _GatedInsert(store)
    monkeypatch.setattr(store, "insert_memory_exact", gated)
    yield gated
    gated.release.set()


def _server() -> MCPServer:
    server = MCPServer(name="cancel-728-remember")
    tool_registry_memory.register(server)
    return server


async def _wait_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, _GUARD)


async def _until(condition: Callable[[], bool]) -> None:
    """Yield to the loop until ``condition()`` holds, bounded by ``_GUARD``."""

    async def poll() -> None:
        while not condition():
            await asyncio.sleep(_POLL)

    await asyncio.wait_for(poll(), _GUARD)


def _slot_returned() -> bool:
    sem = _get_semaphore(_TOOL)
    return sem._value == current_budget(_TOOL)


def _assert_abandoned_and_held(gate: _GatedInsert, before: int) -> None:
    assert abandoned_work.snapshot()["in_flight"] == {_TOOL: 1}
    sem = _get_semaphore(_TOOL)
    assert sem._value == current_budget(_TOOL) - 1
    assert gate.ids == []
    assert gate.total() == before


async def _finish_worker(gate: _GatedInsert, before: int) -> None:
    gate.release.set()
    await _until(_slot_returned)
    await _until(lambda: not abandoned_work.snapshot()["in_flight"])
    snap = abandoned_work.snapshot()
    assert snap["ended"][_TOOL]["completed"] == 1
    assert len(gate.ids) == 1
    memory = gate.store.get_memory(gate.ids[0])
    assert memory is not None
    assert memory["content"] == _CONTENT
    assert gate.total() == before + 1


def _args() -> dict[str, Any]:
    return {"content": _CONTENT, "force": True, "tags": ["issue-728"]}


@pytest.mark.asyncio
async def test_cancelled_remember_keeps_slot_and_row_lands(gate: _GatedInsert):
    before = gate.total()
    async with Client(_server(), mode="legacy") as client:
        call = asyncio.ensure_future(client.call_tool(_TOOL, _args()))
        await _wait_thread_event(gate.reached)
        # The JSON-RPC dispatcher sends notifications/cancelled.
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await _until(lambda: bool(abandoned_work.snapshot()["in_flight"]))
        _assert_abandoned_and_held(gate, before)

        await _finish_worker(gate, before)


@pytest.mark.asyncio
async def test_disconnected_remember_keeps_slot_and_row_lands(gate: _GatedInsert):
    before = gate.total()
    async with Client(_server(), mode="legacy") as client:
        call = asyncio.ensure_future(client.call_tool(_TOOL, _args()))
        await _wait_thread_event(gate.reached)
    # Leaving the client closes the transport: the server cancels its
    # in-flight handlers and stops while the worker is still blocked.
    call.cancel()
    await asyncio.gather(call, return_exceptions=True)
    await _until(lambda: bool(abandoned_work.snapshot()["in_flight"]))
    _assert_abandoned_and_held(gate, before)

    await _finish_worker(gate, before)
