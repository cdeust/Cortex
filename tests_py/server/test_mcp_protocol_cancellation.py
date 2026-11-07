"""Issue #728 over the MCP protocol: client cancel and disconnect mid-call.

``test_safe_handler_cancellation`` cancels the awaiting task directly. Here
the cancellation arrives the way a client sends it: a ``tools/call`` through
the SDK client and server over the in-memory transport, then either the
client's ``notifications/cancelled`` (the caller task is cancelled) or the
client leaving (the transport closes). The handler writes one row to an
SQLite file of its own under ``tmp_path``.

What the tests pin, for both paths:
- the worker keeps its admission slot until it ends, not until the cancel;
- ``abandoned_work`` counts it while it runs and records ``completed``;
- its write lands after the client stopped listening (in-flight mutation
  semantics: a started write is not rolled back by a cancel);
- teardown does not wait on, nor kill, the worker thread.

Orderings are driven by ``threading.Event``, never by elapsed time. The store
is a plain SQLite file, not a Cortex store: the tests pin the protocol and
admission boundary, not a particular handler's writes.

source: issue #728 (acceptance: "Exercise real MCP cancellation/disconnect
with isolated stores and verify side effects and teardown")
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
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


async def _wait_slot_returned() -> None:
    """The slot is released by a done-callback on the loop: let it run."""
    sem = _get_semaphore(_TOOL)
    for _ in range(100):
        if sem._value == current_budget(_TOOL):  # noqa: SLF001
            return
        await asyncio.sleep(0)
    raise AssertionError(f"slot not returned: {sem!r}")


def _assert_abandoned_and_held() -> None:
    assert abandoned_work.snapshot()["in_flight"] == {_TOOL: 1}
    sem = _get_semaphore(_TOOL)
    assert sem._value == current_budget(_TOOL) - 1  # noqa: SLF001


async def _finish_worker(writer: _WritingHandler) -> None:
    writer.release.set()
    await _wait_thread_event(writer.ended)
    await _wait_slot_returned()
    snap = abandoned_work.snapshot()
    assert snap["in_flight"] == {}
    assert snap["ended"][_TOOL]["completed"] == 1


@pytest.mark.asyncio
async def test_client_cancel_keeps_slot_and_write_lands(tmp_path: Path):
    writer = _WritingHandler(tmp_path / "store.db")
    try:
        async with Client(_server(writer)) as client:
            call = asyncio.ensure_future(client.call_tool(_TOOL, {"n": 1}))
            await _wait_thread_event(writer.started)
            call.cancel()  # the SDK sends notifications/cancelled
            with pytest.raises(asyncio.CancelledError):
                await call
            await asyncio.wait_for(_until_abandoned(), _GUARD)
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
        async with Client(_server(writer)) as client:
            call = asyncio.ensure_future(client.call_tool(_TOOL, {"n": 1}))
            await _wait_thread_event(writer.started)
        # Leaving the client closes the transport; the server stops.
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        await asyncio.wait_for(_until_abandoned(), _GUARD)
        _assert_abandoned_and_held()
        assert writer.rows() == []

        await _finish_worker(writer)
        assert writer.rows() == [1]
    finally:
        writer.release.set()


async def _until_abandoned() -> None:
    while not abandoned_work.snapshot()["in_flight"]:
        await asyncio.sleep(0)
