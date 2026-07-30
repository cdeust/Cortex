"""Regression tests pinning the stdio drain-before-shutdown contract.

See ``mcp_server/infrastructure/stdio_transport.py``'s module docstring for
the full upstream mechanism. Summary: ``mcp`` 1.29.0's
``BaseSession._receive_loop`` closes the write stream unconditionally when
the read stream reaches EOF -- even if a request dispatched from the SAME
input batch is still executing concurrently in a handler task and has not
called ``respond()`` yet. Both classes below drive that exact race
deterministically (no sleeps, no retries): a "slow" tool signals
``handler_started`` the instant it begins running, then blocks on
``handler_may_finish`` until the test explicitly releases it -- proving the
handler is genuinely in flight at the moment EOF is simulated, never a
timing guess.

``TestUnguardedRaceCharacterization`` reproduces the bug against the bare
SDK call (``mcp._mcp_server.run`` directly, no Cortex fix in the loop) --
proof the race is real and upstream, not a test artifact. It additionally
synchronizes on the real write stream's own ``aclose()`` via a spy wrapper
(``CloseObservingWriteStream``) so the drop is asserted deterministically
rather than "usually" -- the same intermittency the original bug report
describes would otherwise make this characterization flaky too.

``TestGuardedRunDeliversLateResponse`` drives the SAME race through
``_run_low_level_drained`` and asserts the response survives -- the actual
regression pin. It fails if the fix in ``stdio_transport.py`` is reverted
or bypassed (verified 2026-07-30 by re-running this file against
``mcp._mcp_server.run`` in place of ``_run_low_level_drained``: the
response is lost, matching the characterization test's own assertion).

See ``test_stdio_transport_wiring.py`` for the `stateless`-parameter and
outer-wrapper coverage split out to keep this file under the 500-line cap.
"""

from __future__ import annotations

import anyio
import mcp.types as types
import pytest
from mcp.shared.message import SessionMessage

from mcp_server.infrastructure.stdio_transport import _run_low_level_drained
from tests_py.infrastructure._stdio_transport_helpers import (
    CloseObservingWriteStream,
    collect_responses,
    feed_batch_then_simulate_eof,
    make_slow_tool_server,
)


class TestUnguardedRaceCharacterization:
    """Documents the upstream defect directly -- no Cortex fix involved.

    If this test starts failing (the response stops being dropped) on a
    future ``mcp``/``fastmcp`` upgrade, the upstream race has been fixed
    and ``stdio_transport.py``'s workaround is a candidate for removal --
    do not silently adjust this assertion without re-reading that module's
    docstring first.
    """

    @pytest.mark.asyncio
    async def test_unguarded_low_level_run_drops_the_late_response(self) -> None:
        handler_started = anyio.Event()
        handler_may_finish = anyio.Event()
        write_stream_closed = anyio.Event()
        mcp = make_slow_tool_server(
            handler_started=handler_started, handler_may_finish=handler_may_finish
        )

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
        observed_write_stream = CloseObservingWriteStream(
            write_stream, write_stream_closed
        )

        init_options = mcp._mcp_server.create_initialization_options()

        responses: dict[int, SessionMessage] = {}

        async def _collect() -> None:
            nonlocal responses
            responses = await collect_responses(write_stream_reader)

        async def _drive_and_release() -> None:
            await feed_batch_then_simulate_eof(read_stream_writer, handler_started)
            # Deterministic: only release the handler once the spy has
            # observed _receive_loop actually close the write stream --
            # otherwise this characterization would inherit the ORIGINAL
            # bug's own intermittency instead of demonstrating it reliably.
            await write_stream_closed.wait()
            handler_may_finish.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_collect)
            tg.start_soon(_drive_and_release)
            # Bare upstream call -- the exact vulnerable path, no wrapper.
            await mcp._mcp_server.run(read_stream, observed_write_stream, init_options)

        assert 1 in responses, (
            "initialize is handled inline; never subject to this race"
        )
        assert 2 not in responses, (
            "characterization failed: the late tools/call response was NOT "
            "dropped -- either upstream fixed the race, or this harness "
            "changed. Re-read stdio_transport.py's module docstring before "
            "adjusting this assertion."
        )


class TestGuardedRunDeliversLateResponse:
    """The actual regression pin: fails if stdio_transport.py's fix is
    reverted, bypassed, or its write-stream guard stops working."""

    @pytest.mark.asyncio
    async def test_guarded_run_delivers_the_late_response(self) -> None:
        handler_started = anyio.Event()
        handler_may_finish = anyio.Event()
        mcp = make_slow_tool_server(
            handler_started=handler_started, handler_may_finish=handler_may_finish
        )

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        responses: dict[int, SessionMessage] = {}

        async def _collect() -> None:
            nonlocal responses
            responses = await collect_responses(write_stream_reader)

        async def _drive_and_release() -> None:
            await feed_batch_then_simulate_eof(read_stream_writer, handler_started)
            # No write-stream-closed wait needed here: the fix must
            # deliver the response regardless of exactly when EOF lands
            # relative to the handler finishing -- that independence from
            # scheduling order IS the property being pinned.
            handler_may_finish.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_collect)
            tg.start_soon(_drive_and_release)
            await _run_low_level_drained(mcp, read_stream, write_stream)

        assert 1 in responses
        assert 2 in responses, (
            "the guarded run lost the late tools/call response -- the "
            "drain-before-close fix in stdio_transport.py is broken or "
            "was bypassed"
        )
        result = responses[2].message.root
        assert isinstance(result, types.JSONRPCResponse)
        assert result.result["content"][0]["text"] == "done"
        assert result.result["isError"] is False

        # Pins _run_low_level_drained's own init_options construction --
        # specifically NotificationOptions(tools_changed=True), and NOT
        # `None` (which FastMCP's LowLevelServer.create_initialization_options
        # would silently substitute with its OWN broader instance default,
        # NotificationOptions(prompts_changed=True, resources_changed=True,
        # tools_changed=True) -- so `tools.listChanged` alone reads `True`
        # either way; `prompts`/`resources` are what distinguish the two
        # constructions on the wire, measured 2026-07-30 against this exact
        # code path). This choice mirrors FastMCP's own
        # `run_stdio_async` verbatim (this function's whole contract is
        # behavioral parity with it, see module docstring), not a Cortex
        # preference -- do not "fix" this by broadening it to match
        # LowLevelServer's default.
        init_result = responses[1].message.root
        assert isinstance(init_result, types.JSONRPCResponse)
        capabilities = init_result.result["capabilities"]
        assert capabilities["tools"]["listChanged"] is True
        assert capabilities["prompts"]["listChanged"] is False, (
            "initialize response capabilities don't match "
            "NotificationOptions(tools_changed=True) -- "
            "_run_low_level_drained's init_options construction is broken "
            "or is passing None (see comment above)"
        )
        assert capabilities["resources"]["listChanged"] is False
