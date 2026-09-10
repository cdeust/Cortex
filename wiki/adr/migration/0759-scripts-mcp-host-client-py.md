# ADR-0759: scripts/mcp_host_client.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/mcp_host_client.py`; original SHA-256 `0506693ddb36c853d47de6745310e8db117c28cdf7015f5334cc6514b2838495`.

## Original docstring, lines 1–35

````text
"""Drive one MCP stdio server the way a real host drives it.

The distinction this module exists to honour: **closing stdin is the MCP
shutdown signal, not an end-of-input marker.** MCP 2025-06-18 §Lifecycle
› Shutdown › stdio: "the client SHOULD initiate shutdown by: 1. First,
closing the input stream to the child process (the server) 2. Waiting for
the server to exit, or sending SIGTERM ... 3. Sending SIGKILL ...". The
protocol defines no drain phase and no ordered termination: once stdin is
closed the server is being torn down, and nothing obliges it to answer
requests it had already accepted.

This harness used to drive the server with ``subprocess.run(input=...)``,
which writes the whole batch and closes stdin immediately -- i.e. it
signalled shutdown before reading a single response, then asserted that
every response had arrived. No MCP host behaves that way; the assertion
was not a contract the server owes anyone. Against mcp 2.0.0 it fails for
real: `JSONRPCDispatcher.run`'s `finally: tg.cancel_scope.cancel()` fires
on read-EOF, and a handler whose response write is cancelled at
`MemoryObjectSendStream.send`'s entry checkpoint is answered with nothing
at all -- `_handle_request` set `answer_write_started` on the line *before*
the write, so its shutdown-error arm declines to speak ("prefer
possibly-zero answers over possibly-two"). Reproduced against a bare
mcp 2.0.0 server with zero Cortex code (2026-08-10, isolated venv, wheel
sha256 1cb4c75d2d2c7b8c1d756355e5d82a39f2822cc7f13e22a2051d7ca3592349d6,
the hash `uv.lock` pins): ids 4 and 5 of a six-frame batch got no frame.

So the exchange below keeps stdin OPEN until every expected response id
has arrived, and closes it only then -- the ordered termination the
protocol leaves to the client. Synchronisation is by event (a response
line arriving, or stdout reaching EOF), never by elapsed time; the only
clock in here is the caller's ``timeout``, a watchdog that kills a wedged
child so the run cannot hang forever. It never decides a verdict: a killed
child closes stdout, the read loop ends, and the missing ids are reported
exactly as if the server had answered nothing.
"""
````

## Original comment, lines 49–50

````text
# source: MCP protocol revision this harness's handshake declares -- mcp
# 2.0.0 accepts it on the "legacy" (pre-2026-07-28-envelope) handshake path.
````

## Original docstring, lines 122–131

````text
"""The spawned server's env: this harness's own leaks stripped.

    A PYTHONPATH inherited from ci.yml's "Validate MCP host configurations"
    job (it sets PYTHONPATH=$GITHUB_WORKSPACE so this script can import
    repo-root helpers) would make the child's ``mcp_server`` import resolve
    from the CHECKOUT rather than from whatever its own venv installed --
    silently testing a checkout-source + venv-dependencies Frankenstein no
    real install ever runs. A user bootstrapping via ``uvx`` never has it
    set. Surfaced 2026-08-10, PR #331.
    """
````

## Original comment, lines 144–147

````text
# Regression environment: FastMCP's banner-time update check used to
        # import SOCKS support and abort before initialize. The MCP runtime
        # must not make that non-essential network request. Cold uvx bootstrap
        # explicitly disables this fixture because it must reach PyPI.
````

## Original docstring, lines 157–161

````text
"""Record one stdout line, refusing anything that is not an MCP frame.

    Spec MUST (2025-06-18 §Transports › stdio): "The server MUST NOT write
    anything to its stdout that is not a valid MCP message."
    """
````

## Original docstring, lines 183–198

````text
"""Write ``frame_text``, read until every id in ``expected_ids`` is
    answered, then and only then close stdin -- the protocol's shutdown
    signal.

    This is the generic primitive `_exchange` below specializes to the
    fixed six-message contract batch: any caller driving an MCP stdio
    server with its own batch (see `scripts/docker_smoke_client.py`, whose
    batch is the three-message `initialize` / `notifications/initialized`
    / `tools/list` docker_smoke.sh sends) gets the same ordering guarantee
    -- read every expected response first, close stdin second -- without
    re-deriving it.

    Terminates on either event: the last awaited id arriving, or stdout
    reaching EOF (the server exited or a watchdog killed it). Neither is
    a clock.
    """
````

## Original docstring, lines 224–229

````text
"""Spawn the server, exchange one batch as a conformant host, reap it.

    stderr goes to a file rather than a pipe: a pipe nobody drains while
    the exchange is reading stdout would block the child once its stderr
    buffer filled.
    """
````

