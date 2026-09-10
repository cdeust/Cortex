#!/usr/bin/env python3
"""Python driver for `scripts/docker_smoke.sh`'s bare-container exchange.

source: ADR-0733"""

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

# source: ADR-0733
PROTOCOL_VERSION = "2024-11-05"
# source: ADR-0733
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
    """Watchdog target: stop the Docker container.

    source: ADR-0733"""
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
        # source: ADR-0733
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
    """Every response carrying a JSON-RPC error is a failure, including responses other
    than id=3.

    source: ADR-0733"""
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


def _build_parser() -> argparse.ArgumentParser:
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
    return parser


def _evaluate(
    responses: dict[int, dict[str, object]], stderr_text: str, min_tools: int
) -> int:
    """Apply docker_smoke.sh's original pass/fail conditions, in order:
    protocol errors first, then the tools/list contract, then the count
    floor."""
    if errors := protocol_errors(responses):
        return _fail(
            "the container returned JSON-RPC error frames:\n" + "\n".join(errors),
            stderr_text,
        )

    try:
        count = tool_count(responses)
    except SmokeFailureError as error:
        return _fail(str(error), stderr_text)

    if count < min_tools:
        return _fail(
            f"bare-container tools/list returned {count} tools, expected >= "
            f"{min_tools}. This is the exact regression fixed in commit "
            "5d71069c (fix/bare-container-contract).",
            stderr_text,
        )

    print(
        f"docker_smoke: PASS — bare-container tools/list returned {count} "
        f"tools (>= {min_tools}).",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    print(
        f"docker_smoke: running {args.image} with zero env vars, sending "
        "initialize + tools/list over stdio ...",
        file=sys.stderr,
    )
    try:
        responses, stderr_text = run(args.image, args.timeout)
    except ContractError as error:
        return _fail(str(error))

    return _evaluate(responses, stderr_text, args.min_tools)


if __name__ == "__main__":
    raise SystemExit(main())
