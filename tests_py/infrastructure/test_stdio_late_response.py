"""Regression pin, NARROW: a handler still *running inside* ``on_request``
when read-EOF lands is answered with an explicit shutdown error rather than
dropped. That is the only case this file covers, and the scope matters —
see the correction at the bottom of this docstring.

Historical context (removed 2026-08-10, PR #331's mcp 1.29.0 -> 2.0.0
migration): ``mcp_server/infrastructure/stdio_transport.py`` was a
hand-built fix for a FastMCP 3.4.5 defect — its ``LowLevelServer.run``
override dropped the base SDK's own ``finally: tg.cancel_scope.cancel()``,
so on stdin EOF the write stream could close before a request dispatched
from the SAME input batch (e.g. ``tools/call`` right after ``initialize``)
had a chance to respond — dropped with "no stderr output, no exception,
and no JSON-RPC error frame" (that module's own docstring). That module's
fix drained in-flight handlers to completion and delivered their REAL
result even after EOF.

mcp 2.0.0 removed FastMCP as a wrapping layer and rewrote the dispatcher
(``mcp.shared.jsonrpc_dispatcher.JSONRPCDispatcher.run``). Its own source
comments read, at first glance, like the same guarantee: "the write stream
closes only after the task-group join, so teardown writes still land".
**That is not the whole story — verify past the comment, not just it**
(first-pass testing here initially mis-concluded "the race is fixed" by
checking only "did request id=2 get *a* response", not *which* response).
The full sequence, read from ``JSONRPCDispatcher.run``'s actual source:
on EOF, the dispatcher calls ``tg.cancel_scope.cancel()`` in its own
``finally`` — which CANCELS every in-flight handler task immediately (an
``await`` inside the handler is a cancellation checkpoint) — and
``_handle_request``'s cancellation branch answers each cancelled request
with an explicit ``ErrorData(code=CONNECTION_CLOSED, message="Connection
closed")`` BEFORE the outer ``async with self._write_stream:`` closes it.
So: the write stream really does stay open long enough for every in-flight
request to get *some* answer — but the answer is a shutdown error, not the
handler's real result, because the handler was cancelled, not drained.

CORRECTION (2026-08-10, third and final round on this question). An earlier
revision of this docstring generalised the above into "the silent-drop
defect IS fixed — every request gets an explicit, loud response". **That
generalisation is false, and this scenario cannot see why.** It holds the
handler *inside* ``on_request`` when the cancel arrives, which is the one
state where ``answer_write_started`` is still False and the shutdown-error
arm therefore speaks. Move the handler one statement further — let it
return, so ``_handle_request`` sets ``answer_write_started = True`` on the
line *before* awaiting the response write — and a cancel landing on that
write is answered with nothing at all: the flag makes the shutdown arm
stand down ("prefer possibly-zero answers over possibly-two"), and the
write itself never delivered. Reproduced against a bare mcp 2.0.0 server
with zero Cortex code; forced deterministically in
``test_stdio_eof_drain.py``, which is the file to read for the full model.

So: this test's green is evidence about ONE interleaving, never about
"stdio is safe". Do not re-derive a general claim from it — that inference
has now been made and retracted twice.
"""

from __future__ import annotations

from dataclasses import dataclass

import anyio
import mcp.types as types
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.shared.message import SessionMessage


class _CloseObservingWriteStream:
    """Write-stream proxy that records when ``aclose()`` actually runs.

    Precondition: ``real`` is an open send stream this proxy does not own
    the lifecycle of. Postcondition: every ``send()`` reaches ``real``
    unchanged; ``aclose()``/``__aexit__()`` close ``real`` AND set
    ``closed_event`` exactly once each call.
    """

    def __init__(self, real: object, closed_event: anyio.Event) -> None:
        self._real = real
        self._closed_event = closed_event

    async def send(self, item: SessionMessage) -> None:
        await self._real.send(item)  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        await self._real.aclose()  # type: ignore[attr-defined]
        self._closed_event.set()

    async def __aenter__(self) -> "_CloseObservingWriteStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


def _make_slow_tool_server(
    *, handler_started: anyio.Event, handler_may_finish: anyio.Event
) -> MCPServer:
    mcp = MCPServer(name="race-pin")

    @mcp.tool()
    async def slow_tool() -> str:
        handler_started.set()
        await handler_may_finish.wait()
        return "done"

    return mcp


async def _feed_batch_then_simulate_eof(
    read_stream_writer: object, handler_started: anyio.Event
) -> None:
    """Send initialize + initialized + a tools/call, then close (EOF).

    The tools/call is the LAST message before EOF — the exact shape the
    original race needed: a handler dispatched from the tail of the input
    batch, still running when the read side closes.
    """
    init_req = types.JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params={
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "race-pin", "version": "0.0.1"},
        },
    )
    await read_stream_writer.send(SessionMessage(init_req))  # type: ignore[attr-defined]

    init_notif = types.JSONRPCNotification(
        jsonrpc="2.0", method="notifications/initialized"
    )
    await read_stream_writer.send(SessionMessage(init_notif))  # type: ignore[attr-defined]

    call_req = types.JSONRPCRequest(
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params={"name": "slow_tool", "arguments": {}},
    )
    await read_stream_writer.send(SessionMessage(call_req))  # type: ignore[attr-defined]

    await handler_started.wait()
    await read_stream_writer.aclose()  # type: ignore[attr-defined]  # simulate stdin EOF


async def _collect_responses(write_stream_reader: object) -> dict[int, SessionMessage]:
    responses: dict[int, SessionMessage] = {}
    async with write_stream_reader:  # type: ignore[attr-defined]
        async for item in write_stream_reader:  # type: ignore[attr-defined]
            msg = item.message
            if isinstance(msg, (types.JSONRPCResponse, types.JSONRPCError)):
                responses[msg.id] = item
    return responses


@dataclass
class _RaceFixtures:
    """Everything one race run needs — grouped so building it is one call."""

    mcp: MCPServer
    handler_started: anyio.Event
    handler_may_finish: anyio.Event
    write_stream_closed: anyio.Event
    read_stream_writer: object
    read_stream: object
    write_stream_reader: object
    observed_write_stream: _CloseObservingWriteStream
    init_options: object


def _build_race_fixtures() -> _RaceFixtures:
    handler_started = anyio.Event()
    handler_may_finish = anyio.Event()
    write_stream_closed = anyio.Event()
    mcp = _make_slow_tool_server(
        handler_started=handler_started, handler_may_finish=handler_may_finish
    )
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
    observed_write_stream = _CloseObservingWriteStream(
        write_stream, write_stream_closed
    )
    return _RaceFixtures(
        mcp=mcp,
        handler_started=handler_started,
        handler_may_finish=handler_may_finish,
        write_stream_closed=write_stream_closed,
        read_stream_writer=read_stream_writer,
        read_stream=read_stream,
        write_stream_reader=write_stream_reader,
        observed_write_stream=observed_write_stream,
        init_options=mcp._lowlevel_server.create_initialization_options(),
    )


async def _drive_late_request_scenario() -> dict[int, SessionMessage]:
    """Run the deterministic EOF-vs-in-flight-handler race once; return
    whatever responses the dispatcher wrote back for request ids 1/2.

    Extracted from the test method itself (Fowler 2018 Ch. 6, Extract
    Function) to keep it under this repo's 40-line/method convention
    (CLAUDE.md) without shortening the setup this scenario needs.
    """
    f = _build_race_fixtures()
    responses: dict[int, SessionMessage] = {}

    async def _collect() -> None:
        nonlocal responses
        responses = await _collect_responses(f.write_stream_reader)

    async def _drive_and_release() -> None:
        await _feed_batch_then_simulate_eof(f.read_stream_writer, f.handler_started)
        # The dispatcher cancels the in-flight handler as part of its own
        # EOF/shutdown sequence (see module docstring) — it never waits
        # for handler_may_finish, so releasing it is only to let the task
        # settle (a cancelled await returns immediately either way) and
        # keep this harness deterministic rather than relying on
        # cancellation timing.
        await f.write_stream_closed.wait()
        f.handler_may_finish.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(_collect)
        tg.start_soon(_drive_and_release)
        await f.mcp._lowlevel_server.run(
            f.read_stream, f.observed_write_stream, f.init_options
        )

    return responses


class TestStdioLateResponseNeverSilentlyDrops:
    """Pin: a request whose handler is still SUSPENDED INSIDE ``on_request``
    at EOF is answered with a shutdown error. Narrow by construction — a
    handler that already returned is a different case, and a losing one
    (``test_stdio_eof_drain.py``)."""

    @pytest.mark.asyncio
    async def test_bare_lowlevel_run_answers_the_late_request(self) -> None:
        responses = await _drive_late_request_scenario()

        assert 1 in responses, (
            "initialize is handled inline; never subject to this race"
        )
        assert 2 in responses, (
            "the late tools/call request got NO response at all — the "
            "original silent-drop defect is back (see module docstring); "
            "re-verify against a real mcp release before changing this"
        )
        result = responses[2].message
        # NOT asserting the handler's real "done" result: the dispatcher
        # cancels in-flight handlers on EOF (see module docstring) rather
        # than draining them, so the only guaranteed shape is an explicit
        # error frame — never silence.
        assert isinstance(result, types.JSONRPCError), (
            "expected mcp 2.0.0's documented shutdown-error answer for a "
            "cancelled in-flight request; got a different shape — "
            "re-read this module's docstring before adjusting the assertion"
        )
        assert result.error.code == types.CONNECTION_CLOSED
