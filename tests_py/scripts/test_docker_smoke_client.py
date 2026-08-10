"""`scripts/docker_smoke_client.py` must drain the container's exchange
before it signals shutdown, for the exact three-frame batch
`docker_smoke.sh` sends (`initialize` id=1, `notifications/initialized`,
`tools/list` id=3).

This is the same ordering contract `tests_py/scripts/test_mcp_host_client.py`
pins for the six-message contract batch, applied to this module's own
batch/ids — no subprocess and no docker, no clock: the exchange reads every
expected response first, and stdin is provably still open at each of those
reads. The mechanism this guards against — closing stdin (the container's
shutdown signal, 2025-06-18 SS Lifecycle -> Shutdown -> stdio) before a
response has been read causes mcp 2.0.0 to drop it silently, regardless of
which method it answers — is forced deterministically against the real SDK
in `tests_py/infrastructure/test_stdio_eof_drain.py`; here we pin the client
side for this script's own request shape.
"""

from __future__ import annotations

import pytest

from scripts import docker_smoke_client as smoke_client
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
    """Replays scripted server output, recording stdin's state at each read."""

    def __init__(self, lines: list[str], stdin: _RecordingStdin) -> None:
        self._lines = list(lines)
        self._stdin = stdin
        self.stdin_closed_at_read: list[bool] = []

    def readline(self) -> str:
        self.stdin_closed_at_read.append(self._stdin.closed)
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def read(self) -> str:
        return "".join(self._lines)


def _response_line(request_id: int) -> str:
    return '{"jsonrpc":"2.0","id":%d,"result":{"tools":[]}}\n' % request_id


def _scripted_drain(lines: list[str]) -> tuple[dict, _RecordingStdin, _ScriptedStdout]:
    stdin = _RecordingStdin()
    stdout = _ScriptedStdout(lines, stdin)
    responses = host_client.drain_exchange(
        stdin, stdout, smoke_client.frame_text(), smoke_client.expected_ids()
    )
    return responses, stdin, stdout


class TestDockerSmokeBatchDrainsBeforeShutdown:
    def test_expected_ids_are_exactly_init_and_tools_list(self) -> None:
        assert smoke_client.expected_ids() == frozenset({1, smoke_client.TOOLS_LIST_ID})

    def test_both_responses_are_collected(self) -> None:
        responses, _, _ = _scripted_drain(
            [_response_line(1), _response_line(smoke_client.TOOLS_LIST_ID)]
        )
        assert set(responses) == {1, smoke_client.TOOLS_LIST_ID}

    def test_stdin_stays_open_until_the_tools_list_response_is_read(self) -> None:
        _, stdin, stdout = _scripted_drain(
            [_response_line(1), _response_line(smoke_client.TOOLS_LIST_ID)]
        )
        assert stdout.stdin_closed_at_read == [False, False], (
            "the exchange closed the container's stdin — its shutdown signal — "
            "before reading the tools/list response; that is the exact defect "
            "this module exists to prevent (the bash `printf | docker run` "
            "anti-pattern it replaced)"
        )
        assert stdin.closed, "stdin must be closed once the batch is answered"

    def test_the_batch_written_matches_docker_smoke_shs_original_requests(self) -> None:
        _, stdin, _ = _scripted_drain(
            [_response_line(1), _response_line(smoke_client.TOOLS_LIST_ID)]
        )
        written = "".join(stdin.written)
        assert '"method":"initialize"' in written
        assert '"method":"notifications/initialized"' in written
        assert '"method":"tools/list"' in written
        assert '"id":1' in written
        assert f'"id":{smoke_client.TOOLS_LIST_ID}' in written

    def test_a_response_arriving_after_eof_that_precedes_it_is_lost(self) -> None:
        """The scenario the old bash script was blind to: if the container's
        `tools/list` write had not yet reached the pipe when EOF fired
        (`tests_py/infrastructure/test_stdio_eof_drain.py` forces this
        against the real SDK), a reader that only looks at what arrived
        before EOF never sees it. `drain_exchange` cannot exhibit this — it
        keeps stdin open exactly until id=3 is read — but a reader that
        stops at the first EOF, matching the old script's
        `wait "$DOCKER_RUN_PID"; RAW_OUTPUT="$(cat "$RAW_OUTPUT_FILE")"`
        shape, would report only what happened to be flushed already."""
        # id=3's line never appears — this is what "EOF strictly before the
        # response could be delivered" looks like from the reading side.
        responses, stdin, stdout = _scripted_drain([_response_line(1)])
        assert set(responses) == {1}
        assert smoke_client.TOOLS_LIST_ID not in responses
        assert stdin.closed


class TestToolCount:
    def test_missing_tools_list_response_is_a_smoke_failure(self) -> None:
        with pytest.raises(
            smoke_client.SmokeFailureError, match="no valid tools/list response"
        ):
            smoke_client.tool_count({1: {"result": {}}})

    def test_non_object_result_is_a_smoke_failure(self) -> None:
        with pytest.raises(smoke_client.SmokeFailureError, match="no object result"):
            smoke_client.tool_count({smoke_client.TOOLS_LIST_ID: {"result": None}})

    def test_non_list_tools_field_is_a_smoke_failure(self) -> None:
        with pytest.raises(smoke_client.SmokeFailureError, match="expected a list"):
            smoke_client.tool_count(
                {smoke_client.TOOLS_LIST_ID: {"result": {"tools": "nope"}}}
            )

    def test_the_advertised_tool_count_is_returned(self) -> None:
        tools = [{"name": f"t{i}"} for i in range(52)]
        count = smoke_client.tool_count(
            {smoke_client.TOOLS_LIST_ID: {"result": {"tools": tools}}}
        )
        assert count == 52


class TestProtocolErrors:
    def test_no_errors_on_clean_responses(self) -> None:
        responses = {
            1: {"result": {}},
            smoke_client.TOOLS_LIST_ID: {"result": {"tools": []}},
        }
        assert smoke_client.protocol_errors(responses) == []

    def test_an_error_frame_on_any_id_is_reported(self) -> None:
        responses = {
            1: {"result": {}},
            2: {
                "error": {
                    "code": -32602,
                    "message": "28 validation errors for ClientRequest",
                }
            },
        }
        errors = smoke_client.protocol_errors(responses)
        assert len(errors) == 1
        assert "code=-32602" in errors[0]
        assert "28 validation errors" in errors[0]
