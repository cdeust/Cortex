#!/usr/bin/env python3
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

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.mcp_host_client import ContractError, drain_exchange  # noqa: E402

# source: scripts/docker_smoke.sh's original REQUESTS heredoc (git history,
# commit 18d4505 and its bare-container-contract predecessor 5d71069c) --
# the exact three-frame handshake a bare-container registry indexer
# (Glama et al.) sends: `initialize`, `notifications/initialized` (a
# notification -- carries no "id", JSON-RPC 2.0 SS4.1), then `tools/list`.
PROTOCOL_VERSION = "2024-11-05"
TOOLS_LIST_ID = 3


def _messages() -> list[dict[str, object]]:
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "docker-smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": TOOLS_LIST_ID, "method": "tools/list", "params": {}},
    ]


def frame_text() -> str:
    return "".join(
        json.dumps(message, separators=(",", ":")) + "\n" for message in _messages()
    )


def expected_ids() -> frozenset[int]:
    return frozenset(
        message["id"] for message in _messages() if isinstance(message.get("id"), int)
    )


class SmokeFailureError(RuntimeError):
    """The bare-container contract was not satisfied."""


def _kill_container(cidfile: Path, process: subprocess.Popen[str]) -> None:
    """Watchdog target: stop the CONTAINER, not just the local `docker run`
    client -- see this module's docstring for why a client-side kill is not
    sufficient.
    """
    if cidfile.exists() and cidfile.stat().st_size > 0:
        cid = cidfile.read_text().strip()
        if cid:
            subprocess.run(
                ["docker", "kill", cid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        # No container ever started (client-side hang) -- fall back to
        # signaling the client process directly.
        process.kill()


def run(image: str, timeout: int) -> tuple[dict[int, dict[str, object]], str]:
    """Run the container, drain the exchange, and reap it.

    Returns (responses, container_stderr). Raises `ContractError` if the
    container's stdout carried a line that is not valid JSON-RPC (spec
    MUST, 2025-06-18 SS Transports -> stdio: "The server MUST NOT write
    anything to its stdout that is not a valid MCP message").
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        cidfile = Path(tmp_dir) / "cid"
        # stderr goes to a file rather than a pipe: a pipe nobody drains
        # while the exchange is reading stdout would block the container
        # once its stderr buffer filled (same rationale as
        # `mcp_host_client.run_client`).
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
            process = subprocess.Popen(
                ["docker", "run", "--rm", "-i", f"--cidfile={cidfile}", image],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
            )
            stdin, stdout = process.stdin, process.stdout
            if (
                stdin is None or stdout is None
            ):  # pragma: no cover - PIPE requested above
                raise ContractError("docker run: pipes were not created")
            watchdog = threading.Timer(
                timeout, _kill_container, args=(cidfile, process)
            )
            watchdog.start()
            try:
                responses = drain_exchange(stdin, stdout, frame_text(), expected_ids())
                process.wait()
            finally:
                watchdog.cancel()
                stdout.close()
            stderr_file.seek(0)
            stderr_text = stderr_file.read()
    return responses, stderr_text


def protocol_errors(responses: dict[int, dict[str, object]]) -> list[str]:
    """Any response frame carrying a JSON-RPC error -- not just id=3 -- is a
    failure even when `tools/list` happens to answer: it means the
    container rejected a frame this script sent, and the last time that
    was tolerated it made this gate intermittent rather than simply red
    (see `docker_smoke.sh`'s git history, commit 18d4505)."""
    lines = []
    for request_id, message in sorted(responses.items()):
        if "error" in message:
            error = message["error"]
            lines.append(
                f"  id={request_id} code={error.get('code')} "
                f"message={error.get('message')}"
            )
    return lines


def tool_count(responses: dict[int, dict[str, object]]) -> int:
    message = responses.get(TOOLS_LIST_ID)
    if message is None:
        raise SmokeFailureError(
            f"no valid tools/list response (id={TOOLS_LIST_ID}) found in "
            "container stdout."
        )
    result = message.get("result")
    if not isinstance(result, dict):
        raise SmokeFailureError(f"tools/list returned no object result: {result!r}")
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise SmokeFailureError(f"tools/list returned tools={tools!r}, expected a list")
    return len(tools)


def _fail(message: str, stderr_text: str | None = None) -> int:
    print(f"docker_smoke: FAIL — {message}", file=sys.stderr)
    if stderr_text is not None:
        print("--- container stderr ---", file=sys.stderr)
        print(stderr_text, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="image tag to run")
    parser.add_argument(
        "--min-tools",
        type=int,
        required=True,
        help="minimum tools/list count to accept",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="watchdog deadline in seconds"
    )
    args = parser.parse_args(argv)

    print(
        f"docker_smoke: running {args.image} with zero env vars, sending "
        "initialize + tools/list over stdio ...",
        file=sys.stderr,
    )
    try:
        responses, stderr_text = run(args.image, args.timeout)
    except ContractError as error:
        return _fail(str(error))

    if errors := protocol_errors(responses):
        return _fail(
            "the container returned JSON-RPC error frames:\n" + "\n".join(errors),
            stderr_text,
        )

    try:
        count = tool_count(responses)
    except SmokeFailureError as error:
        return _fail(str(error), stderr_text)

    if count < args.min_tools:
        return _fail(
            f"bare-container tools/list returned {count} tools, expected >= "
            f"{args.min_tools}. This is the exact regression fixed in commit "
            "5d71069c (fix/bare-container-contract).",
            stderr_text,
        )

    print(
        f"docker_smoke: PASS — bare-container tools/list returned {count} "
        f"tools (>= {args.min_tools}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
