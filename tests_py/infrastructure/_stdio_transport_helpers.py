"""Shared test-support for the ``stdio_transport`` regression suite.

Split out of ``test_stdio_transport.py`` (which had reached 534 lines
against this repo's 500-line cap) so both that file and
``test_stdio_transport_wiring.py`` can import the same fixtures without
duplication. Not itself a test module -- no ``test_*`` names, so pytest
does not collect it (same convention as ``tests_py/_store_cleanup.py``).
"""

from __future__ import annotations

import contextlib

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastmcp import FastMCP
from mcp.shared.message import SessionMessage


def make_slow_tool_server(
    *, handler_started: anyio.Event, handler_may_finish: anyio.Event
) -> FastMCP:
    """A minimal FastMCP instance with one tool-call handler that proves it
    is running (sets ``handler_started``) then blocks on
    ``handler_may_finish`` before returning -- the controllable "in-flight
    handler" the race needs. Registered directly on the low-level server
    (``mcp._mcp_server.call_tool``) rather than via FastMCP's `@mcp.tool`
    decorator, so tests exercise exactly the object `_run_low_level_drained`
    operates on, without FastMCP's tool-execution layer (thread offload,
    timeouts, tracing) adding unrelated variables.
    """
    mcp = FastMCP(name="test-drain", version="0.0.0")

    async def _slow_tool(tool_name: str, arguments: dict) -> list[types.TextContent]:
        handler_started.set()
        await handler_may_finish.wait()
        return [types.TextContent(type="text", text="done")]

    mcp._mcp_server.call_tool(validate_input=False)(_slow_tool)
    return mcp


def init_message(request_id: int) -> SessionMessage:
    request = types.JSONRPCRequest(
        jsonrpc="2.0",
        id=request_id,
        method="initialize",
        params={
            "protocolVersion": types.LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "drain-test", "version": "0"},
        },
    )
    return SessionMessage(message=types.JSONRPCMessage(request))


def call_tool_message(request_id: int) -> SessionMessage:
    request = types.JSONRPCRequest(
        jsonrpc="2.0",
        id=request_id,
        method="tools/call",
        params={"name": "slow_tool", "arguments": {}},
    )
    return SessionMessage(message=types.JSONRPCMessage(request))


# source: measured -- the whole 6552-test suite this file belongs to runs
# in ~165s (~25ms/test average, 2026-07-30), and a working handler dispatch
# in these tests observably completes in low tens of milliseconds. 5s is
# two orders of magnitude above that: generous enough to never flake on a
# slow CI runner, short enough that a handler which will genuinely never
# start (e.g. because `initialize` itself failed, so the MCP lifecycle
# correctly refuses the next request -- see
# mcp.server.session.ServerSession._received_request's
# `InitializationState` check) fails a test in seconds, not by silently
# hanging until pytest's own 300s global timeout (pyproject.toml) fires.
HANDLER_START_BOUND_SECONDS = 5


async def feed_batch_then_simulate_eof(
    read_stream_writer: MemoryObjectSendStream[SessionMessage],
    handler_started: anyio.Event,
) -> None:
    """Send ``initialize`` + ``tools/call``, wait until the handler is
    provably running, then close the writer -- simulating a client that
    closes stdin right after writing a complete request batch (exactly
    what ``scripts/docker_smoke.sh`` does with one ``printf``).
    """
    await read_stream_writer.send(init_message(1))
    await read_stream_writer.send(call_tool_message(2))
    # Deterministic: only proceeds once _slow_tool has actually started
    # executing (dispatched by Server.run()'s task group and scheduled) --
    # never a sleep-based guess at interleaving. Bounded (see
    # HANDLER_START_BOUND_SECONDS) so a broken `initialize` -- which
    # cascades into the MCP lifecycle correctly refusing tools/call, so the
    # handler never starts at all -- fails the test fast instead of
    # hanging it.
    with anyio.fail_after(HANDLER_START_BOUND_SECONDS):
        await handler_started.wait()
    await read_stream_writer.aclose()


async def collect_responses(
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage],
) -> dict[int, SessionMessage]:
    responses: dict[int, SessionMessage] = {}
    async with write_stream_reader:
        async for session_message in write_stream_reader:
            root = session_message.message.root
            request_id = getattr(root, "id", None)
            if request_id is not None:
                responses[request_id] = session_message
    return responses


class CloseObservingWriteStream:
    """Test-only spy: forwards ``send``/``aclose`` to ``real``, additionally
    signalling ``closed_event`` once ``aclose()`` fires -- so a test can
    deterministically wait for "the SDK actually closed this stream"
    without polling a private attribute or guessing at timing.
    """

    def __init__(
        self,
        real: MemoryObjectSendStream[SessionMessage],
        closed_event: anyio.Event,
    ) -> None:
        self._real = real
        self._closed_event = closed_event

    async def send(self, item: SessionMessage) -> None:
        await self._real.send(item)

    async def aclose(self) -> None:
        await self._real.aclose()
        self._closed_event.set()

    async def __aenter__(self) -> CloseObservingWriteStream:
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        await self.aclose()


def fake_async_cm(yielded: object):
    """A minimal async-context-manager factory for mocking `stdio_server()`
    / `mcp._lifespan_manager()` without configuring MagicMock's async dunder
    protocol by hand."""

    @contextlib.asynccontextmanager
    async def _cm():
        yield yielded

    return _cm
