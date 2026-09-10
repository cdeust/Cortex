# ADR-0733: scripts/docker_smoke_client.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/docker_smoke_client.py`; original SHA-256 `94d289aedec67fad9390ef293133856b5815bff8f8ce9e486531c84a89cdb79e`.

## Original docstring, lines 2–40

````text
"""Python driver for `scripts/docker_smoke.sh`'s bare-container exchange.

`docker_smoke.sh` used to pipe its whole request batch into `docker run -i`
via `printf '%s' "$REQUESTS" | docker run --rm -i ... "$IMAGE"`: `printf`
closes its end of the pipe -- the container's stdin -- the instant it has
written the last byte, before a single response has been read. That is
exactly the anti-pattern `mcp_host_client.py` exists to retire (see its
module docstring): closing stdin is the MCP shutdown signal (2025-06-18
SS Lifecycle -> Shutdown -> stdio), not an end-of-input marker, and mcp
2.0.0's `_handle_request` drops an in-flight response write rather than
deliver it once EOF has fired the cancel scope -- regardless of which
method the request named. Verified 2026-08-10 against
`mcp/shared/jsonrpc_dispatcher.py::_dispatch_request`/`_handle_request`
(mcp 2.0.0, the version `uv.lock` pins): every accepted request, including
`tools/list`, is dispatched through this one generic path -- there is no
per-method branch that would make `tools/list` immune. That is the
mechanism behind this gate's signature failure, "no valid tools/list
response (id=3)": the container's answer was started, then cancelled by an
EOF that arrived before it could be delivered, and the SDK's own rule
("prefer possibly-zero answers over possibly-two",
`jsonrpc_dispatcher.py::_handle_request`) means it settles as no answer at
all -- silently, no error frame, exactly the "stderr empty, no JSON-RPC
error frame" signature this gate has shown intermittently since it was
added.

This module keeps the container's stdin open until the expected response
ids have arrived (`mcp_host_client.drain_exchange`), closing it only then
-- the same fix `mcp_host_client.py` applies to a local subprocess,
applied here to a `docker run -i` child. `docker run -i` forwards this
process's stdin/stdout to the container's stdin/stdout as an ordinary pipe
pair, so the identical fix applies verbatim; the only genuinely
docker-specific piece is the watchdog, which must `docker kill` the
CONTAINER (via `--cidfile`) rather than signal the local `docker run`
client process -- measured 2026-07-30 against a deliberately hanging test
image (`ENTRYPOINT sh -c "sleep infinity"`) where a client-side SIGTERM did
not stop it (`docker ps` still showed it running well past the deadline).
This is a deadline (a worst-case bound on one run), not a retry: it fires
at most once and never re-attempts the request.
"""
````

## Original comment, lines 58–62

````text
# source: scripts/docker_smoke.sh's original REQUESTS heredoc (git history,
# commit 18d4505 and its bare-container-contract predecessor 5d71069c) --
# the exact three-frame handshake a bare-container registry indexer
# (Glama et al.) sends: `initialize`, `notifications/initialized` (a
# notification -- carries no "id", JSON-RPC 2.0 SS4.1), then `tools/list`.
````

## Original comment, lines 64–66

````text
# source: same docker_smoke.sh REQUESTS heredoc as PROTOCOL_VERSION above --
# `tools/list` was request id=3 in that batch (id=1 is `initialize`;
# `notifications/initialized` is a notification and carries no id at all).
````

## Original comment, lines 133–136

````text
# stderr goes to a file rather than a pipe: a pipe nobody drains
        # while the exchange is reading stdout would block the container
        # once its stderr buffer filled (same rationale as
        # `mcp_host_client.run_client`).
````

## Reviewed remaining docstring (scripts/docker_smoke_client.py, interim lines 62–65)

````text
Watchdog target: stop the CONTAINER, not just the local `docker run`
client -- see this module's docstring for why a client-side kill is not
sufficient.
````

## Reviewed remaining docstring (scripts/docker_smoke_client.py, interim lines 121–125)

````text
Any response frame carrying a JSON-RPC error -- not just id=3 -- is a
failure even when `tools/list` happens to answer: it means the
container rejected a frame this script sent, and the last time that
was tolerated it made this gate intermittent rather than simply red
(see `docker_smoke.sh`'s git history, commit 18d4505).
````

