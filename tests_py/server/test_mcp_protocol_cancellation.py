"""Issue #728 over the MCP protocol: client cancel and disconnect mid-call.

``test_safe_handler_cancellation`` cancels the awaiting task directly. Here
the cancellation arrives the way a client sends it: a ``tools/call`` through
the SDK client and server over the in-memory transport, then either the
client's ``notifications/cancelled`` (the caller task is cancelled) or the
client leaving (the transport closes). ``mode="legacy"`` is what puts the
in-process server behind ``InMemoryTransport`` and JSON-RPC: the default
``"auto"`` mode uses the SDK's ``DirectDispatcher``, where cancellation is a
direct await and no notification crosses a transport. The handler writes one
row to an SQLite file of its own under ``tmp_path``.

What both tests pin:
- the worker keeps its admission slot until it ends, not until the cancel;
- ``abandoned_work`` counts it while it runs and records ``completed``;
- a handler still running at the cancel, blocked before its write, makes that
  write after the client stopped listening: the cancel does not stop it.

The cancel test also pins that the session serves a new call afterwards. The
disconnect test also pins that teardown neither waits on nor kills the worker
thread: the client exits while the worker is still blocked.

Orderings are driven by ``threading.Event``. Waits on loop-side effects poll
until the effect holds, bounded only by a deadlock guard. The store
is a plain SQLite file, not a Cortex store: the tests pin the protocol and
admission boundary, not a particular handler's writes.

source: issue #728 (acceptance: "Exercise real MCP cancellation/disconnect
with isolated stores and verify side effects and teardown")
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import abandoned_work
from mcp_server.handlers.admission import (
    _get_semaphore,
    current_budget,
    reset_semaphores,
)
from mcp_server.observability import metrics
from mcp_server.tool_error_handler import safe_handler

# source: mcp_server/handlers/latency_class.py — an interactive tool with no
# override in admission._OVERRIDES has the class default budget of 4.
_TOOL = "detect_gaps"
# source: deadlock guard, not a measurement — a wait that a correct
# implementation satisfies at once, bounded so a broken one fails the test.
_GUARD = 5.0
# source: poll interval of the bounded waits above, not a measurement — short
# against _GUARD so a correct run returns promptly.
_POLL = 0.001


@pytest.fixture(autouse=True)
def _clean_state():
    reset_semaphores()
    metrics.reset()
    abandoned_work.reset()
    yield
    reset_semaphores()
    metrics.reset()
    abandoned_work.reset()


class _WritingHandler:
    """Blocks until released, then inserts one row into its own SQLite file."""

    def __init__(self, db: Path) -> None:
        self.db = db
        self.started = threading.Event()
        self.release = threading.Event()
        self.ended = threading.Event()
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE writes (n INTEGER)")

    async def handler(self, args: dict) -> dict:
        self.started.set()
        try:
            assert self.release.wait(_GUARD)
            with sqlite3.connect(self.db) as conn:
                conn.execute("INSERT INTO writes VALUES (?)", (args["n"],))
            return {"n": args["n"]}
        finally:
            self.ended.set()

    def rows(self) -> list[int]:
        with sqlite3.connect(self.db) as conn:
            return [r[0] for r in conn.execute("SELECT n FROM writes ORDER BY n")]


def _server(writer: _WritingHandler) -> MCPServer:
    server = MCPServer(name="cancel-728")

    @server.tool(name=_TOOL)
    async def tool(n: int) -> dict:
        return await safe_handler(writer.handler, {"n": n}, _TOOL)

    return server


async def _wait_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, _GUARD)


async def _until(condition: Callable[[], bool]) -> None:
    """Yield to the loop until ``condition()`` holds, bounded by ``_GUARD``.

    ``writer.ended`` is set inside the handler, before the worker thread
    closes its loop and the executor future completes, so the done-callbacks
    (slot release, abandoned outcome) may still be pending: wait for their
    effect, not for a number of loop turns."""

    async def poll() -> None:
        while not condition():
            await asyncio.sleep(_POLL)

    await asyncio.wait_for(poll(), _GUARD)


def _slot_returned() -> bool:
    sem = _get_semaphore(_TOOL)
    return sem._value == current_budget(_TOOL)


def _assert_abandoned_and_held() -> None:
    assert abandoned_work.snapshot()["in_flight"] == {_TOOL: 1}
    sem = _get_semaphore(_TOOL)
    assert sem._value == current_budget(_TOOL) - 1


async def _finish_worker(writer: _WritingHandler) -> None:
    writer.release.set()
    await _wait_thread_event(writer.ended)
    await _until(_slot_returned)
    await _until(lambda: not abandoned_work.snapshot()["in_flight"])
    snap = abandoned_work.snapshot()
    assert snap["in_flight"] == {}
    assert snap["ended"][_TOOL]["completed"] == 1


@pytest.mark.asyncio
async def test_client_cancel_keeps_slot_and_write_lands(tmp_path: Path):
    writer = _WritingHandler(tmp_path / "store.db")
    try:
        async with Client(_server(writer), mode="legacy") as client:
            call = asyncio.ensure_future(client.call_tool(_TOOL, {"n": 1}))
            await _wait_thread_event(writer.started)
            # The JSON-RPC dispatcher sends notifications/cancelled.
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            await _until(lambda: bool(abandoned_work.snapshot()["in_flight"]))
            _assert_abandoned_and_held()
            assert writer.rows() == []

            await _finish_worker(writer)
            assert writer.rows() == [1]

            # The session outlives the cancelled call.
            writer.started.clear()
            writer.ended.clear()
            result = await asyncio.wait_for(client.call_tool(_TOOL, {"n": 2}), _GUARD)
            assert not result.is_error
        assert writer.rows() == [1, 2]
    finally:
        writer.release.set()


@pytest.mark.asyncio
async def test_client_disconnect_keeps_slot_and_write_lands(tmp_path: Path):
    writer = _WritingHandler(tmp_path / "store.db")
    try:
        async with Client(_server(writer), mode="legacy") as client:
            call = asyncio.ensure_future(client.call_tool(_TOOL, {"n": 1}))
            await _wait_thread_event(writer.started)
        # Leaving the client closes the transport (read EOF): the server
        # cancels its in-flight handlers and stops.
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        await _until(lambda: bool(abandoned_work.snapshot()["in_flight"]))
        _assert_abandoned_and_held()
        assert writer.rows() == []

        await _finish_worker(writer)
        assert writer.rows() == [1]
    finally:
        writer.release.set()
