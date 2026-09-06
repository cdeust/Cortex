"""Observe a hook's emitted UTF-8 text and process-level completion.

The stream forwards writes immediately: injection text, receipt markers and
print's trailing newlines stay unchanged. ``ok`` describes normal completion
or exit code zero, including the hooks' intentionally tolerated degradations.
"""

from __future__ import annotations

import sys
import time
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
from functools import wraps
from typing import TYPE_CHECKING, BinaryIO, Protocol, TextIO, runtime_checkable

from mcp_server.core import telemetry
from mcp_server.shared.telemetry_context import operation_metrics

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class _CountingOutput:
    """Count unencoded test/custom text streams that have no binary buffer."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.bytes_out = 0

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        # source: UTF-8 encoding of the text accepted by TextIO.write.
        self.bytes_out += len(text[:written].encode("utf-8"))
        return written

    def flush(self) -> None:
        self._stream.flush()


@runtime_checkable
class _BufferedOutput(Protocol):
    """Text streams exposing the binary destination after newline/encoding."""

    @property
    def buffer(self) -> BinaryIO: ...

    def flush(self) -> None: ...


class _CountingBuffer:
    """Count bytes accepted after TextIOWrapper encoding and newline conversion."""

    def __init__(self, buffer: BinaryIO) -> None:
        self.write_original = buffer.write
        self.bytes_out = 0

    def write(self, data: ReadableBuffer) -> int:
        written = self.write_original(data)
        self.bytes_out += written
        return written


@contextmanager
def _observe_output() -> Iterator[_CountingOutput | _CountingBuffer]:
    """Observe the existing encoder; do not reconstruct its newline policy."""
    stream = sys.stdout
    if not isinstance(stream, _BufferedOutput):
        output = _CountingOutput(stream)
        with redirect_stdout(output):
            yield output
        return
    # Flush pre-existing text before attaching the counter to this operation.
    stream.flush()
    counter = _CountingBuffer(stream.buffer)
    stream.buffer.write = counter.write
    failed = False
    try:
        yield counter
    except BaseException:
        failed = True
        raise
    finally:
        try:
            # TextIOWrapper may defer encoding until flush; count that output
            # before restoring the original binary write method.
            _flush_output(stream, failed)
        finally:
            stream.buffer.write = counter.write_original


def _flush_output(stream: _BufferedOutput, failed: bool) -> None:
    """A broken output stream must not replace an already-raised hook error."""
    try:
        stream.flush()
    except (OSError, ValueError):
        if not failed:
            raise
        logger.warning("Cannot flush failed hook output", exc_info=True)


def _run_observed(op: str, hook: Callable[[], None]) -> None:
    """Record once, preserving stdout, exceptions and the hook's exit code."""
    started = time.perf_counter()
    ok = False
    output: _CountingOutput | _CountingBuffer = _CountingOutput(sys.stdout)
    with operation_metrics():
        try:
            with _observe_output() as observed:
                output = observed
                hook()
            ok = True
        except SystemExit as exc:
            # source: Python sys.exit: None and zero signal successful exit.
            ok = exc.code is None or exc.code == 0
            raise
        finally:
            telemetry.record(
                op,
                # source: SI conversion, one second equals 1000 milliseconds.
                latency_ms=(time.perf_counter() - started) * 1000,
                bytes_out=output.bytes_out,
                ok=ok,
            )


def observe_hook(op: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Decorate a CLI main, giving each hook invocation its own metrics."""

    def decorate(hook: Callable[[], None]) -> Callable[[], None]:
        @wraps(hook)
        def observed() -> None:
            _run_observed(op, hook)

        return observed

    return decorate
