"""Regression pin: mcp 2.0.0's own stdio dispatch never SILENTLY DROPS a
response to a request still in flight when read-EOF lands. It answers with
an explicit shutdown error instead — a materially different, narrower
guarantee than the workaround this replaces used to provide; read on.

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

Net effect versus the original bug: the silent-drop defect (dead air, no
frame at all) IS fixed — every request gets an explicit, loud response.
The stronger property Cortex's own workaround provided (in-flight work
completes and its real result reaches the client even after EOF) is NOT
reproduced, and cannot be restored without patching the dispatcher's own
cancel-on-EOF ``finally`` — an invasive construct coding-standards.md §7
refuses by default for a narrower win than the original defect. This test
pins the WEAKER, upstream-native guarantee actually verified: no silent
drop, ever — not "in-flight work survives EOF".

If this test starts FAILING (a request goes unanswered — dead silence,
not even a shutdown error), that is the ORIGINAL silent-drop defect back;
re-read this docstring and ``mcp_server/__main__.py``'s ``main()`` comment
before changing the assertion or reaching for a Cortex-side stdio wrapper.
"""

from __future__ import annotations

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


class TestStdioLateResponseNeverSilentlyDrops:
    """Pin: mcp 2.0.0's bare dispatch, no Cortex wrapper, ALWAYS answers a
    request in flight at EOF — with a shutdown error, never dead silence."""

    @pytest.mark.asyncio
    async def test_bare_lowlevel_run_answers_the_late_request(self) -> None:
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

        init_options = mcp._lowlevel_server.create_initialization_options()

        responses: dict[int, SessionMessage] = {}

        async def _collect() -> None:
            nonlocal responses
            responses = await _collect_responses(write_stream_reader)

        async def _drive_and_release() -> None:
            await _feed_batch_then_simulate_eof(read_stream_writer, handler_started)
            # The dispatcher cancels the in-flight handler as part of its
            # own EOF/shutdown sequence (see module docstring) — it never
            # waits for handler_may_finish, so releasing it is only to let
            # the task settle (a cancelled await returns immediately either
            # way) and keep this harness deterministic rather than relying
            # on cancellation timing.
            await write_stream_closed.wait()
            handler_may_finish.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_collect)
            tg.start_soon(_drive_and_release)
            await mcp._lowlevel_server.run(
                read_stream, observed_write_stream, init_options
            )

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
