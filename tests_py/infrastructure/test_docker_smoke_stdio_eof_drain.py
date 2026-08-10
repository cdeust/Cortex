"""Pins docker_smoke.sh's LITERAL historical failure ('no valid tools/list
response (id=3)', empty stderr, no JSON-RPC error frame) to the EOF-before-
drain mechanism `test_stdio_eof_drain.py` forces deterministically, using
`scripts/docker_smoke_client.py`'s own request id and method — not just the
same defect class under a different id/method.

Reuses that module's `_server`/`_GatedWriteStream`/`_collect` rather than
duplicating them (split into this sibling file only because appending here
would have pushed `test_stdio_eof_drain.py` over its own 300-line cap).

Before `scripts/docker_smoke_client.py` existed, `docker_smoke.sh` drove the
container with exactly the shape `test_shutdown_before_drain_drops_tools_list`
below reproduces: `printf | docker run` writes the whole batch and closes the
container's stdin the instant the write finishes, without ever reading a
response first.
"""

from __future__ import annotations

import anyio
import mcp.types as types
import pytest
from mcp.shared.message import SessionMessage

from tests_py.infrastructure.test_stdio_eof_drain import (
    _collect,
    _GatedWriteStream,
    _server,
)

# source: scripts/docker_smoke_client.py's own request batch (TOOLS_LIST_ID)
# — ties this reproduction to docker_smoke.sh's literal historical failure
# message, not just the same defect class under a different method/id.
_DOCKER_SMOKE_GATED_ID = 3


def _docker_smoke_batch() -> list[types.JSONRPCRequest | types.JSONRPCNotification]:
    return [
        types.JSONRPCRequest(
            jsonrpc="2.0",
            id=1,
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "docker-smoke", "version": "0"},
            },
        ),
        types.JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"),
        types.JSONRPCRequest(
            jsonrpc="2.0",
            id=_DOCKER_SMOKE_GATED_ID,
            method="tools/list",
            params={},
        ),
    ]


def _docker_smoke_request_ids() -> set[int]:
    return {f.id for f in _docker_smoke_batch() if isinstance(f, types.JSONRPCRequest)}


async def _send_docker_smoke_batch(writer: object) -> None:
    for frame in _docker_smoke_batch():
        await writer.send(SessionMessage(frame))  # type: ignore[attr-defined]


class TestDockerSmokeToolsListLostBeforeDrain:
    @pytest.mark.asyncio
    async def test_shutdown_before_drain_drops_tools_list(self) -> None:
        parked = anyio.Event()
        answered: dict[int, object] = {}
        done = anyio.Event()
        server = _server()
        read_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_reader = anyio.create_memory_object_stream(0)
        gated = _GatedWriteStream(write_stream, _DOCKER_SMOKE_GATED_ID, parked)

        async def drive() -> None:
            await _send_docker_smoke_batch(read_writer)
            await parked.wait()  # the tools/list write has started, unlanded
            await read_writer.aclose()  # EOF == shutdown signal

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                _collect, write_reader, answered, done, _docker_smoke_request_ids()
            )
            tg.start_soon(drive)
            await server._lowlevel_server.run(
                read_stream,
                gated,
                server._lowlevel_server.create_initialization_options(),
            )

        assert 1 in answered, "initialize is handled inline; never subject to this"
        assert _DOCKER_SMOKE_GATED_ID not in answered, (
            "docker_smoke.sh's exact failure, reproduced deterministically: "
            "the container's tools/list (id=3) answer was started and then "
            "cancelled by an EOF that arrived before it could be delivered — "
            "'no valid tools/list response (id=3)', empty stderr, no error "
            "frame. This is what the old `printf | docker run` shape could "
            "hit; scripts/docker_smoke_client.py cannot, by construction "
            "(see the test below)."
        )

    @pytest.mark.asyncio
    async def test_drain_then_shutdown_answers_tools_list(self) -> None:
        answered: dict[int, object] = {}
        done = anyio.Event()
        server = _server()
        read_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_reader = anyio.create_memory_object_stream(0)

        async def drive() -> None:
            await _send_docker_smoke_batch(read_writer)
            await done.wait()  # tools/list answered — THEN shut down
            await read_writer.aclose()

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                _collect, write_reader, answered, done, _docker_smoke_request_ids()
            )
            tg.start_soon(drive)
            await server._lowlevel_server.run(
                read_stream,
                write_stream,
                server._lowlevel_server.create_initialization_options(),
            )

        assert _docker_smoke_request_ids() <= answered.keys()
        assert isinstance(answered[_DOCKER_SMOKE_GATED_ID], types.JSONRPCResponse), (
            "draining first must yield a real tools/list result, not a shutdown error"
        )
