"""Why a host must drain BEFORE it signals shutdown, forced deterministically.

Both scenarios below drive the same bare ``mcp`` 2.0.0 server over the same
in-memory stream pair. They differ in one ordering decision — when the read
side is closed — and that decision alone decides whether an accepted request
is answered at all.

The missing guarantee, named: **an accepted request is never promised an
answer.** `JSONRPCDispatcher._handle_request` sets ``answer_write_started``
on the line *before* it awaits the response write, and its shutdown arm then
declines to send the ``CONNECTION_CLOSED`` frame whenever that flag is set
("prefer possibly-zero answers over possibly-two"). So a response write that
was cancelled *without ever delivering* is nonetheless counted as possibly
sent, and the request settles with no frame of any kind. Read-EOF is what
fires the cancel (`run()`'s ``finally: tg.cancel_scope.cancel()``), and
nothing orders "the response reached the writer" before it.

`_GatedWriteStream` reproduces that class of interleaving deterministically:
it parks the response write, which puts the handler in exactly the state the
flag describes — write started, nothing delivered — and only then is EOF
signalled. No sleeps, no wall-clock: every step waits on an event.

MCP 2025-06-18 §Lifecycle › Shutdown › stdio makes closing stdin the shutdown
signal, and defines no drain phase, so this is the SDK honouring the protocol,
not violating it. The correction therefore belongs to the client: read your
answers first, close stdin second. That is what `scripts/mcp_host_client.py`
does and what `test_drain_then_shutdown_answers_every_request` pins.
"""

from __future__ import annotations

import anyio
import mcp.types as types
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.shared.message import SessionMessage

_GATED_ID = 2


class _GatedWriteStream:
    """Forwards every frame, except one it parks forever.

    Precondition: ``real`` is an open send stream whose lifecycle this proxy
    does not own beyond forwarding ``aclose``. Postcondition: the first frame
    whose id is ``gate_id`` never reaches ``real``; ``parked`` is set the
    instant that frame is withheld, so the driver can order EOF strictly
    after the write has started and strictly before it could deliver.
    """

    def __init__(self, real: object, gate_id: int, parked: anyio.Event) -> None:
        self._real = real
        self._gate_id = gate_id
        self._parked = parked
        self._already_gated = False

    async def send(self, item: SessionMessage) -> None:
        if (
            getattr(item.message, "id", None) == self._gate_id
            and not self._already_gated
        ):
            self._already_gated = True
            self._parked.set()
            await anyio.sleep_forever()  # released only by the shutdown cancel
        await self._real.send(item)  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        await self._real.aclose()  # type: ignore[attr-defined]

    async def __aenter__(self) -> "_GatedWriteStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


def _server() -> MCPServer:
    mcp = MCPServer(name="eof-drain")

    @mcp.tool()
    async def echo() -> str:
        return "ok"

    return mcp


def _batch() -> list[types.JSONRPCRequest | types.JSONRPCNotification]:
    return [
        types.JSONRPCRequest(
            jsonrpc="2.0",
            id=1,
            method="initialize",
            params={
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "eof-drain", "version": "0.0.1"},
            },
        ),
        types.JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"),
        types.JSONRPCRequest(
            jsonrpc="2.0",
            id=_GATED_ID,
            method="tools/call",
            params={"name": "echo", "arguments": {}},
        ),
    ]


def _request_ids() -> set[int]:
    return {f.id for f in _batch() if isinstance(f, types.JSONRPCRequest)}


async def _collect(
    reader: object, answered: dict[int, object], done: anyio.Event
) -> None:
    async with reader:  # type: ignore[attr-defined]
        async for item in reader:  # type: ignore[attr-defined]
            message = item.message
            if isinstance(message, (types.JSONRPCResponse, types.JSONRPCError)):
                answered[message.id] = message
                if _request_ids() <= answered.keys():
                    done.set()


async def _send_batch(writer: object) -> None:
    for frame in _batch():
        await writer.send(SessionMessage(frame))  # type: ignore[attr-defined]


class TestEofBeforeDrainLosesAnAcceptedRequest:
    """The old harness shape: signal shutdown, then hope for answers."""

    @pytest.mark.asyncio
    async def test_shutdown_before_drain_drops_the_response_silently(self) -> None:
        parked = anyio.Event()
        answered: dict[int, object] = {}
        done = anyio.Event()
        server = _server()
        read_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_reader = anyio.create_memory_object_stream(0)
        gated = _GatedWriteStream(write_stream, _GATED_ID, parked)

        async def drive() -> None:
            await _send_batch(read_writer)
            await parked.wait()  # the write has started and cannot have landed
            await read_writer.aclose()  # EOF == shutdown signal

        async with anyio.create_task_group() as tg:
            tg.start_soon(_collect, write_reader, answered, done)
            tg.start_soon(drive)
            await server._lowlevel_server.run(
                read_stream,
                gated,
                server._lowlevel_server.create_initialization_options(),
            )

        assert 1 in answered, "initialize is handled inline; never subject to this"
        assert _GATED_ID not in answered, (
            "mcp 2.0.0 answered a request whose write was cancelled before it "
            "delivered — upstream now distinguishes 'write started' from "
            "'possibly delivered'. Good news: re-read this module's docstring, "
            "then relax scripts/mcp_host_client.py only if the new guarantee "
            "is documented upstream, never because one interleaving improved."
        )


class TestDrainThenShutdownAnswersEveryRequest:
    """The conformant shape `scripts/mcp_host_client.py` implements."""

    @pytest.mark.asyncio
    async def test_drain_then_shutdown_answers_every_request(self) -> None:
        answered: dict[int, object] = {}
        done = anyio.Event()
        server = _server()
        read_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_reader = anyio.create_memory_object_stream(0)

        async def drive() -> None:
            await _send_batch(read_writer)
            await done.wait()  # every expected id answered — THEN shut down
            await read_writer.aclose()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_collect, write_reader, answered, done)
            tg.start_soon(drive)
            await server._lowlevel_server.run(
                read_stream,
                write_stream,
                server._lowlevel_server.create_initialization_options(),
            )

        assert _request_ids() <= answered.keys()
        assert all(
            isinstance(answered[i], types.JSONRPCResponse) for i in _request_ids()
        ), "draining first must yield real results, not shutdown errors"
