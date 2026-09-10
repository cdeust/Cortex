# ADR-1005: tests_py/infrastructure/test_stdio_late_response.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_stdio_late_response.py`, original SHA-256 `566d64352e2282ac9d45277316759701b1d45460a37e5f439d97d0b523b6e714`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–53

````text
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
````

