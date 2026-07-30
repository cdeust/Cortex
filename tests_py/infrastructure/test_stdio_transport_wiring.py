"""Mutation-driven hardening for ``mcp_server/infrastructure/stdio_transport.py``.

Split out of ``test_stdio_transport.py`` (which had reached 534 lines
against this repo's 500-line cap) -- that file pins the drain-before-close
regression itself; this one pins two things a scoped mutmut run
(``scripts/mutation_check.sh``) found under-covered there:

``TestStatelessParameter`` -- pins `_run_low_level_drained`'s `stateless`
parameter itself (not just that `create_initialization_options` is called):
default `False` means a request sent before `initialize` is refused, per
the MCP lifecycle enforced by
`mcp.server.session.ServerSession._received_request`'s
`InitializationState` check (`case _: if self._initialization_state !=
Initialized: raise RuntimeError(...)`); `stateless=True` starts the session
already `Initialized`, so the same request is accepted immediately. Sending
ONLY `tools/call` (no `initialize` at all) isolates this parameter's effect
from everything else the function does. A mutation of the parameter's own
DEFAULT value survives any test that always passes `stateless=` explicitly
(by the time `initialize` succeeds, `_initialization_state` is already
`Initialized` regardless of what it started as) -- hence the dedicated
omitted-keyword test below, distinct from the explicit-`False` one.

``TestRunStdioDrainedWiring`` -- covers the outer `run_stdio_drained`
wrapper (banner / transport-context-var / lifespan / `stdio_server()`) with
`_run_low_level_drained` itself mocked out; that function's own correctness
is what `test_stdio_transport.py` pins directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import mcp.types as types
import pytest
from mcp.shared.message import SessionMessage

from mcp_server.infrastructure import stdio_transport as _stdio_transport_module
from mcp_server.infrastructure.stdio_transport import _run_low_level_drained
from tests_py.infrastructure._stdio_transport_helpers import (
    HANDLER_START_BOUND_SECONDS,
    call_tool_message,
    collect_responses,
    fake_async_cm,
    make_slow_tool_server,
)


class TestStatelessParameter:
    async def _run_tools_call_only(
        self, *, stateless: bool | None
    ) -> dict[int, SessionMessage]:
        """`stateless=None` OMITS the keyword entirely -- exercises
        `_run_low_level_drained`'s own default parameter value, as opposed
        to `stateless=False` which explicitly passes the same boolean and
        would mask a mutation of the default itself.
        """
        handler_started = anyio.Event()
        handler_may_finish = anyio.Event()
        handler_may_finish.set()  # release immediately if/when dispatched
        mcp = make_slow_tool_server(
            handler_started=handler_started, handler_may_finish=handler_may_finish
        )
        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
        responses: dict[int, SessionMessage] = {}

        async def _collect() -> None:
            nonlocal responses
            responses = await collect_responses(write_stream_reader)

        async def _drive() -> None:
            await read_stream_writer.send(call_tool_message(9))
            await read_stream_writer.aclose()

        kwargs = {} if stateless is None else {"stateless": stateless}
        with anyio.fail_after(HANDLER_START_BOUND_SECONDS):
            async with anyio.create_task_group() as tg:
                tg.start_soon(_collect)
                tg.start_soon(_drive)
                await _run_low_level_drained(mcp, read_stream, write_stream, **kwargs)
        return responses

    @pytest.mark.asyncio
    async def test_omitted_stateless_defaults_to_refusing_a_request_before_initialize(
        self,
    ) -> None:
        """Exercises `_run_low_level_drained`'s own default value for
        `stateless` (the keyword is never passed) -- distinct from the
        explicit-`False` test below, which cannot detect a mutation of the
        default itself since it always overrides it.
        """
        responses = await self._run_tools_call_only(stateless=None)
        result = responses[9].message.root
        assert isinstance(result, types.JSONRPCError), (
            "omitting `stateless` (using _run_low_level_drained's own "
            "default) should behave like stateless=False -- refuse "
            "tools/call sent before initialize"
        )
        assert result.error.code == types.INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_explicit_stateless_false_refuses_a_request_before_initialize(
        self,
    ) -> None:
        responses = await self._run_tools_call_only(stateless=False)
        result = responses[9].message.root
        assert isinstance(result, types.JSONRPCError), (
            "explicit stateless=False should refuse tools/call sent "
            "before initialize, per the MCP lifecycle"
        )
        assert result.error.code == types.INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_stateless_true_accepts_a_request_before_initialize(
        self,
    ) -> None:
        responses = await self._run_tools_call_only(stateless=True)
        result = responses[9].message.root
        assert isinstance(result, types.JSONRPCResponse), (
            "stateless=True should accept tools/call sent before "
            "initialize -- the session starts already Initialized"
        )
        assert result.result["content"][0]["text"] == "done"


class TestRunStdioDrainedWiring:
    """Pins the outer `run_stdio_drained` wrapper's own orchestration --
    `_run_low_level_drained` is mocked here; its correctness is pinned by
    `test_stdio_transport.py`, which calls it directly.
    """

    def _make_mcp(self) -> MagicMock:
        mcp = MagicMock()
        mcp.name = "test-drain"
        mcp._lifespan_manager = fake_async_cm(None)
        return mcp

    @pytest.mark.asyncio
    async def test_wires_banner_transport_and_delegates_correctly(self) -> None:
        fake_read_stream = object()
        fake_write_stream = object()
        mcp = self._make_mcp()

        with (
            patch.object(_stdio_transport_module, "log_server_banner") as mock_banner,
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ) as mock_set,
            patch.object(_stdio_transport_module, "reset_transport") as mock_reset,
            patch.object(
                _stdio_transport_module, "temporary_log_level"
            ) as mock_log_level,
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((fake_read_stream, fake_write_stream)),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ) as mock_drained,
        ):
            await _stdio_transport_module.run_stdio_drained(
                mcp, show_banner=True, log_level="DEBUG", stateless=True
            )

        mock_banner.assert_called_once_with(server=mcp)
        mock_set.assert_called_once_with("stdio")
        mock_reset.assert_called_once_with("TOKEN")
        # `temporary_log_level` is a real context manager elsewhere (its own
        # side effect -- the actual logging level -- isn't asserted there),
        # so this is the one place the `log_level` argument threading is
        # pinned: mock it and check the argument reaches it unchanged.
        mock_log_level.assert_called_once_with("DEBUG")
        mock_drained.assert_called_once_with(
            mcp, fake_read_stream, fake_write_stream, stateless=True
        )

    @pytest.mark.asyncio
    async def test_omitted_show_banner_defaults_to_showing_it(self) -> None:
        """Distinct from the explicit-True case above: omits `show_banner`
        entirely, exercising `run_stdio_drained`'s own default rather than
        a value the test supplies."""
        mcp = self._make_mcp()

        with (
            patch.object(_stdio_transport_module, "log_server_banner") as mock_banner,
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport"),
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((object(), object())),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ),
        ):
            await _stdio_transport_module.run_stdio_drained(mcp)

        mock_banner.assert_called_once_with(server=mcp)

    @pytest.mark.asyncio
    async def test_start_log_message_names_server_and_transport(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Pins the exact log-message content (`mode` string included) via
        `caplog` -- mutating it to `None`, a differently-cased/padded
        variant, or an empty placeholder all changes no OTHER observable
        behavior, so only asserting on the log record itself can catch it
        (source: same technique as
        tests_py/shared/test_json_native.py::TestTolistFailureLogging).
        """
        mcp = self._make_mcp()
        mcp.name = "methodology-agent"

        with (
            patch.object(_stdio_transport_module, "log_server_banner"),
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport"),
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((object(), object())),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ),
            caplog.at_level("INFO"),
        ):
            await _stdio_transport_module.run_stdio_drained(mcp, stateless=True)

        assert len(caplog.records) == 1
        expected = (
            "Starting MCP server 'methodology-agent' with transport 'stdio' (stateless)"
        )
        assert caplog.records[0].message == expected

    @pytest.mark.asyncio
    async def test_start_log_message_omits_stateless_suffix_when_not_stateless(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mcp = self._make_mcp()
        mcp.name = "methodology-agent"

        with (
            patch.object(_stdio_transport_module, "log_server_banner"),
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport"),
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((object(), object())),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ),
            caplog.at_level("INFO"),
        ):
            await _stdio_transport_module.run_stdio_drained(mcp, stateless=False)

        # Exact-message equality, not substring containment: a mode suffix
        # mutated to a non-empty placeholder (e.g. "XXXX") would still
        # contain the prefix checked below and satisfy a substring test,
        # so only the full record message pins the empty-suffix case.
        assert len(caplog.records) == 1
        assert (
            caplog.records[0].message
            == "Starting MCP server 'methodology-agent' with transport 'stdio'"
        )

    @pytest.mark.asyncio
    async def test_show_banner_false_skips_the_banner(self) -> None:
        mcp = self._make_mcp()

        with (
            patch.object(_stdio_transport_module, "log_server_banner") as mock_banner,
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport"),
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((object(), object())),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ),
        ):
            await _stdio_transport_module.run_stdio_drained(mcp, show_banner=False)

        mock_banner.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_stateless_is_false(self) -> None:
        """Distinct from the explicit-True wiring test: omits `stateless`
        entirely, exercising `run_stdio_drained`'s own default rather than
        a value the test supplies."""
        fake_read_stream = object()
        fake_write_stream = object()
        mcp = self._make_mcp()

        with (
            patch.object(_stdio_transport_module, "log_server_banner"),
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport"),
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((fake_read_stream, fake_write_stream)),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
            ) as mock_drained,
        ):
            await _stdio_transport_module.run_stdio_drained(mcp)

        mock_drained.assert_called_once_with(
            mcp, fake_read_stream, fake_write_stream, stateless=False
        )

    @pytest.mark.asyncio
    async def test_reset_transport_runs_even_if_the_guarded_run_raises(self) -> None:
        mcp = self._make_mcp()

        with (
            patch.object(_stdio_transport_module, "log_server_banner"),
            patch.object(
                _stdio_transport_module, "set_transport", return_value="TOKEN"
            ),
            patch.object(_stdio_transport_module, "reset_transport") as mock_reset,
            patch.object(
                _stdio_transport_module,
                "stdio_server",
                fake_async_cm((object(), object())),
            ),
            patch.object(
                _stdio_transport_module,
                "_run_low_level_drained",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await _stdio_transport_module.run_stdio_drained(mcp)

        mock_reset.assert_called_once_with("TOKEN")
