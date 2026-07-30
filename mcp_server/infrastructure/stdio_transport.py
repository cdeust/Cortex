"""Stdio transport driver: drains in-flight request handlers before the
write stream is closed on read-EOF.

## Root cause (upstream ``mcp`` 1.29.0 + ``fastmcp`` 3.4.5)

``mcp.shared.session.BaseSession._receive_loop`` (~L351-355) reads::

    async with (self._read_stream, self._write_stream):
        async for message in self._read_stream:
            ...

The SAME write-stream object handed to the session at construction is
closed unconditionally the instant ``self._read_stream`` is exhausted (real
EOF on stdin) -- even when a request dispatched from an EARLIER line in the
very same input batch (e.g. ``tools/list`` after ``initialize``) is still
running in its own task and has not called ``respond()`` yet.

The drop is silent: ``mcp.server.lowlevel.server.Server._handle_request``
(~L805-815) wraps ``await message.respond(response)`` in
``except (anyio.BrokenResourceError, anyio.ClosedResourceError): logger
.debug("Response for %s dropped - transport closed", ...)``. That logger is
the bare ``mcp.server.lowlevel.server`` stdlib logger, which FastMCP's
``configure_logging()`` never touches (it only configures the "fastmcp"
logger tree) and which has zero handlers by default -- so the drop produces
no stderr output, no exception, and no JSON-RPC error frame.

The base SDK's own ``Server.run()`` at least names the hazard::

    finally:
        # Transport closed: cancel in-flight handlers. Without this the
        # TG join waits for them, and when they eventually try to
        # respond they hit a closed write stream...
        tg.cancel_scope.cancel()

FastMCP's override, ``fastmcp.server.low_level.LowLevelServer.run``
(~L234-268) -- the one actually invoked by Cortex, since Cortex constructs a
``FastMCP`` server -- drops that ``finally`` entirely, with nothing in its
place. Its task group therefore does the OPPOSITE of cancelling: it
patiently joins (awaits) every dispatched handler task to completion,
giving a slow-but-live handler every opportunity to run right up to the
already-closed write stream and lose its response there.

## Fix

Cortex does not own ``mcp``/``fastmcp`` and cannot edit their source (they
are third-party dependencies). This module interposes a write-stream proxy,
``_UnclosableWriteStream``, between the REAL stdio-bound send stream and the
``BaseSession``/low-level ``Server`` machinery that reads and closes it:

- ``send()`` forwards to the real stream untouched.
- ``aclose()`` / ``__aexit__()`` (what ``_receive_loop``'s own scope-exit
  calls on read-EOF) is a deliberate no-op: the object ``_receive_loop``
  "closes" is never the real stream, so a handler still computing a
  response at that instant can still deliver it.

The REAL stream is closed by THIS module, in ``_run_low_level_drained``'s
``finally`` clause, strictly after ``mcp._mcp_server.run(...)`` has
returned.

happens-before argument (why that ordering is safe): ``_receive_loop``'s
``guarded.aclose()`` call (a no-op) is nested inside
``ServerSession._receive_loop``'s own
``async with self._incoming_message_stream_writer:`` block, so
``_receive_loop``'s COMPLETE exit happens-before that writer closes, which
happens-before ``session.incoming_messages`` (read by ``Server.run()``'s /
``LowLevelServer.run()``'s own ``async for``) reaches end-of-stream, which
happens-before that ``async for`` loop ends, which happens-before the
ENCLOSING ``async with anyio.create_task_group() as tg:`` block's
``__aexit__`` (a join on every ``tg.start_soon``'d handler task -- FastMCP's
override has no cancel to pre-empt this join) completes -- which is what
"``mcp._mcp_server.run(...)`` returns" MEANS. So: "a handler's own
``respond()`` attempt" happens-before "``run()`` returns" happens-before
"the real ``write_stream.aclose()`` this module performs" -- the real close
can never race ahead of a dispatched handler's own attempt to answer.

A request handled entirely inline within ``_receive_loop`` itself
(currently only ``initialize`` -- see
``mcp.server.session.ServerSession._received_request`` and FastMCP's
``MiddlewareServerSession._received_request`` override, both of which call
``responder.respond()`` synchronously before returning) is not subject to
this race at all and is unaffected by this module either way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import fastmcp
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastmcp.server.context import reset_transport, set_transport
from fastmcp.utilities.cli import log_server_banner
from fastmcp.utilities.logging import get_logger, temporary_log_level
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = get_logger(__name__)


class _UnclosableWriteStream:
    """Send-stream proxy: forwards ``send``, no-ops ``aclose``/``__aexit__``.

    Precondition: ``real`` is an open send stream that THIS MODULE (not the
    proxy, and not whatever the proxy is handed to) owns the lifecycle of.
    Postcondition: every ``send()`` call reaches ``real`` unchanged; every
    ``aclose()``/``__aexit__()`` call is a no-op -- it neither closes
    ``real`` nor raises -- regardless of how many times it is called.
    Invariant: ``real`` is closed only by ``real_close()``, called by the
    owner of this proxy -- never by ``_receive_loop``, which only ever sees
    ``aclose()``/``__aexit__()``.

    Not a ``MemoryObjectSendStream`` subclass on purpose: sharing anyio's
    internal ``_state`` via a subclass (e.g. constructed from ``real._state``)
    would give this proxy its OWN sender slot in that shared state
    (``open_send_channels``), and since this proxy's ``aclose()`` never
    releases that slot, the slot would leak forever -- ``real_close()``
    closing only ``real`` would leave ``open_send_channels`` at 1, and
    ``stdout_writer()``'s ``write_stream_reader`` would never observe
    end-of-stream, hanging the process. A plain forwarding object with no
    shared anyio state avoids that failure mode entirely.
    """

    def __init__(self, real: MemoryObjectSendStream[SessionMessage]) -> None:
        self._real = real

    async def send(self, item: SessionMessage) -> None:
        await self._real.send(item)

    async def aclose(self) -> None:
        return None  # FAILS_ON: nothing -- deliberate no-op, see class docstring

    async def __aenter__(self) -> _UnclosableWriteStream:
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        await self.aclose()

    async def real_close(self) -> None:
        await self._real.aclose()


async def _run_low_level_drained(
    mcp: FastMCP,
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
    *,
    stateless: bool = False,
) -> None:
    """Run ``mcp``'s low-level server over an already-open stream pair,
    draining in-flight handlers before ``write_stream`` is closed.

    Precondition: ``write_stream`` is open and not yet passed to any other
    session/server.
    Postcondition: every request dispatched via ``mcp._mcp_server.run``'s
    own task group (i.e. every non-``initialize`` request the client sent
    before EOF) has had its own opportunity to call ``respond()`` while
    ``write_stream`` was still open. ``write_stream`` is closed exactly
    once, after that guarantee holds -- see the module docstring's
    happens-before argument.
    Invariant: this function closes ``write_stream`` exactly once,
    regardless of whether the guarded run raised.

    Decoupled from ``stdio_server()`` so it can be driven directly against
    in-process anyio memory streams in tests, without real OS stdin/stdout.
    """
    guarded = _UnclosableWriteStream(write_stream)
    init_options = mcp._mcp_server.create_initialization_options(
        notification_options=NotificationOptions(tools_changed=True),
    )
    try:
        await mcp._mcp_server.run(
            read_stream,
            # `guarded` is not a MemoryObjectSendStream instance -- it is a
            # duck-typed substitute implementing exactly the protocol
            # BaseSession/Server.run() use on a write stream (`send`,
            # `__aenter__`, `__aexit__`). See _UnclosableWriteStream's
            # docstring for why a real subclass sharing anyio's internal
            # state was rejected instead.
            # source: mutation-tested equivalent (scripts/mutation_check.sh,
            # 2026-07-30) -- mutating this cast()'s type argument (e.g. to
            # `cast(None, guarded)`) survives every test, because
            # `typing.cast(typ, val)` is a pure static-typing annotation:
            # `inspect.getsource(typing.cast)` shows its body is `return
            # val`, so `typ` is never read at runtime and no test can ever
            # observe a change to it (same equivalence argument as
            # json_native.py's `cast("SupportsFloat", obj)`, CHANGELOG
            # 2026-07-29).
            cast(MemoryObjectSendStream[SessionMessage], guarded),
            init_options,
            stateless=stateless,
        )
    finally:
        # Real close, only now: mcp._mcp_server.run() has returned, which --
        # per the happens-before argument in the module docstring -- means
        # every handler task it started already had its own chance at
        # respond() while `guarded` kept the real stream open through its
        # own no-op aclose().
        await guarded.real_close()


def _resolve_show_banner(show_banner: bool | None) -> bool:
    """Resolve the effective show-banner flag exactly as ``fastmcp.server
    .mixins.transport.TransportMixin.run_async`` does before dispatching to
    ``run_stdio_async`` -- an explicit ``show_banner`` wins; ``None`` (the
    default) resolves to ``fastmcp.settings.show_server_banner``.

    Extracted from ``run_stdio_drained`` (Fowler 2018 Ch. 6, Extract
    Function) to keep that function under this repo's 40-line/method
    convention (CLAUDE.md) without dropping the sourced citation below --
    only relocating it (coding-standards.md §8).

    # source: fastmcp==3.4.5 fastmcp/server/mixins/transport.py L216-218 --
    # `run_stdio_async(self, show_banner: bool = True, ...)` itself does NOT
    # resolve the settings; L88-89's `run_async` does that resolution ONE
    # LEVEL UP, before calling `run_stdio_async(show_banner=show_banner,
    # ...)`. `mcp.run(transport="stdio")` (the call this function replaces,
    # per __main__.py) goes through `run_async`, so its `show_banner=None`
    # behavior IS the settings-resolved one; a wrapper mirroring only
    # `run_stdio_async`'s own literal `True` default drops that resolution.
    # (verified against the actually-installed fastmcp==3.4.5 in
    # .venv/lib/python3.12/site-packages/fastmcp/server/mixins/transport.py
    # on 2026-07-30 -- prior citation of L56-57/L184-186 was a consistent
    # -32-line offset from the installed package.)
    """
    if show_banner is None:
        return fastmcp.settings.show_server_banner
    return show_banner


async def run_stdio_drained(
    mcp: FastMCP,
    *,
    show_banner: bool | None = None,
    log_level: str | None = None,
    stateless: bool = False,
) -> None:
    """Run ``mcp`` over stdio; drop-in replacement for
    ``mcp.run(transport="stdio")`` (i.e.
    ``TransportMixin.run_async`` dispatching to ``run_stdio_async`` -- see
    ``mcp_server/__main__.py::main()`` for why this replaces that call, not
    ``run_stdio_async`` directly) that additionally survives the
    read-EOF-vs-in-flight-handler race described in this module's docstring.

    Precondition: ``mcp`` is a constructed, not-yet-run FastMCP server.
    Postcondition: identical observable behavior to ``mcp.run(transport=
    "stdio")`` for every case it already handled correctly -- including
    ``show_banner`` resolution (see ``_resolve_show_banner``) -- PLUS: a
    request dispatched from the last line of a single-write input batch is
    answered on stdout before the transport tears down, rather than
    silently losing its response to the already-closed pipe.
    """
    if _resolve_show_banner(show_banner):
        log_server_banner(server=mcp)

    token = set_transport("stdio")
    try:
        with temporary_log_level(log_level):
            async with mcp._lifespan_manager():
                async with stdio_server() as (read_stream, write_stream):
                    mode = " (stateless)" if stateless else ""
                    logger.info(
                        f"Starting MCP server {mcp.name!r} with transport 'stdio'{mode}"
                    )
                    await _run_low_level_drained(
                        mcp, read_stream, write_stream, stateless=stateless
                    )
    finally:
        reset_transport(token)
