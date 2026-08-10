"""`scripts/mcp_host_client.py` must drain before it signals shutdown.

The ordering under test is the whole point of that module: closing stdin is
the MCP shutdown signal (2025-06-18 §Lifecycle › Shutdown › stdio), so a
harness that closes it before reading its responses has torn the connection
down and then asked for answers. Against mcp 2.0.0 that request is refused
in silence — the deterministic forcing of that interleaving lives in
`tests_py/infrastructure/test_stdio_eof_drain.py`; here we pin the client
side of the contract, with no subprocess and no clock: the exchange reads
every expected response first, and stdin is provably still open at each of
those reads.
"""

from __future__ import annotations

import pytest

from scripts import mcp_host_client as host_client


class _RecordingStdin:
    """Captures what the exchange writes, and when it closes."""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.flushed = 0
        self.closed = False

    def write(self, text: str) -> None:
        self.written.append(text)

    def flush(self) -> None:
        self.flushed += 1

    def close(self) -> None:
        self.closed = True


class _ScriptedStdout:
    """Replays scripted server output, recording stdin's state at each read.

    Every `readline()` notes whether the peer's stdin was already closed —
    the observation the drain contract turns on.
    """

    def __init__(self, lines: list[str], stdin: _RecordingStdin) -> None:
        self._lines = list(lines)
        self._stdin = stdin
        self.stdin_closed_at_read: list[bool] = []
        self.reads_served = 0

    def readline(self) -> str:
        self.stdin_closed_at_read.append(self._stdin.closed)
        if not self._lines:
            return ""
        self.reads_served += 1
        return self._lines.pop(0)

    def read(self) -> str:
        return "".join(self._lines)


def _response_line(request_id: int) -> str:
    return '{"jsonrpc":"2.0","id":%d,"result":{}}\n' % request_id


def _scripted_exchange(
    lines: list[str],
) -> tuple[dict, _RecordingStdin, _ScriptedStdout]:
    stdin = _RecordingStdin()
    stdout = _ScriptedStdout(lines, stdin)
    responses = host_client._exchange(stdin, stdout, "test-host")
    return responses, stdin, stdout


class TestExchangeDrainsBeforeShutdown:
    def test_every_expected_response_is_collected(self) -> None:
        expected = host_client.expected_request_ids()
        responses, _, _ = _scripted_exchange(
            [_response_line(i) for i in sorted(expected)]
        )
        assert set(responses) == set(expected)

    def test_stdin_stays_open_until_the_last_response_is_read(self) -> None:
        expected = sorted(host_client.expected_request_ids())
        _, stdin, stdout = _scripted_exchange([_response_line(i) for i in expected])
        assert stdout.stdin_closed_at_read == [False] * len(expected), (
            "the exchange closed stdin — the MCP shutdown signal — while it "
            "was still waiting on responses; that is the defect this module "
            "exists to prevent"
        )
        assert stdin.closed, "stdin must be closed once the batch is answered"

    def test_the_batch_is_written_and_flushed_before_any_read(self) -> None:
        expected = sorted(host_client.expected_request_ids())
        _, stdin, stdout = _scripted_exchange([_response_line(i) for i in expected])
        assert stdin.flushed >= 1
        assert '"method":"initialize"' in "".join(stdin.written)
        assert stdout.reads_served == len(expected)

    def test_it_stops_at_stdout_eof_rather_than_waiting_forever(self) -> None:
        """A dead or watchdog-killed server ends the loop by event, not clock."""
        responses, stdin, _ = _scripted_exchange([_response_line(1)])
        assert set(responses) == {1}
        assert stdin.closed

    def test_a_non_mcp_stdout_line_is_a_contract_error(self) -> None:
        with pytest.raises(host_client.ContractError):
            _scripted_exchange(["not json at all\n"])
