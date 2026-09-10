"""Drive one MCP stdio server the way a real host drives it.

source: ADR-0759"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import IO, Literal

# source: ADR-0759
PROTOCOL_VERSION = "2025-06-18"


class ContractError(RuntimeError):
    """A child completed without satisfying the MCP host contract."""


@dataclass(frozen=True)
class ContractCase:
    """One host identity/profile combination and its isolated runtime."""

    client_name: str
    profile: Literal["full", "lean"]
    command: tuple[str, ...]
    data_root: Path
    timeout: int
    socks_proxy_regression: bool
    storage_selection: Literal["sqlite", "auto"]

    @property
    def label(self) -> str:
        return f"{self.client_name}/{self.profile}"


def _messages(client_name: str) -> list[dict[str, object]]:
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "contract-test"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "memory_stats", "arguments": {}},
        },
    ]


def expected_request_ids() -> frozenset[int]:
    """The ids the batch below asks for -- what the exchange waits on."""
    return frozenset(
        message["id"]
        for message in _messages("probe")
        if isinstance(message.get("id"), int)
    )


def frames(client_name: str) -> str:
    return "".join(
        json.dumps(message, separators=(",", ":")) + "\n"
        for message in _messages(client_name)
    )


def environment(
    data_root: Path,
    *,
    socks_proxy_regression: bool,
    storage_selection: Literal["sqlite", "auto"] = "sqlite",
) -> dict[str, str]:
    """The spawned server's env: this harness's own leaks stripped.

    source: ADR-0759"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({"CORTEX_CLAUDE_DIR": str(data_root), "CORTEX_MEMORY_AP_ENABLED": "0"})
    if storage_selection == "sqlite":
        env["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    else:
        # Exercise production auto-selection. In particular, do not inherit a
        # repository- or runner-level SQLite override that would make a
        # PostgreSQL-first smoke pass without ever attempting PostgreSQL.
        env.pop("CORTEX_MEMORY_STORE_BACKEND", None)
        env.pop("CORTEX_ALLOW_SQLITE_FALLBACK", None)
    if socks_proxy_regression:
        # source: ADR-0759
        env["ALL_PROXY"] = "socks5://127.0.0.1:9"
        env["all_proxy"] = "socks5://127.0.0.1:9"
    env.pop("FASTMCP_SHOW_SERVER_BANNER", None)
    env.pop("FASTMCP_CHECK_FOR_UPDATES", None)
    env.pop("CORTEX_MCP_PROFILE", None)
    return env


def absorb(line: str, responses: dict[int, dict[str, object]]) -> None:
    """Record one stdout line, refusing anything that is not an MCP frame.

    source: ADR-0759"""
    if not line.strip():
        return
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise ContractError(
            f"malformed JSON-RPC frame on server stdout: {line!r}"
        ) from error
    if not isinstance(message, dict):
        raise ContractError(f"non-object JSON-RPC frame on stdout: {message!r}")
    request_id = message.get("id")
    if isinstance(request_id, int) and not isinstance(request_id, bool):
        responses[request_id] = message


def drain_exchange(
    stdin: IO[str],
    stdout: IO[str],
    frame_text: str,
    expected_ids: Iterable[int],
) -> dict[int, dict[str, object]]:
    """Write ``frame_text``, read until every id in ``expected_ids`` is
        answered, then and only then close stdin -- the protocol's shutdown
        signal.

        Terminates on either event: the last awaited id arriving, or stdout
        reaching EOF (the server exited or a watchdog killed it). Neither is
        a clock.

    source: ADR-0759"""
    outstanding = set(expected_ids)
    responses: dict[int, dict[str, object]] = {}
    stdin.write(frame_text)
    stdin.flush()
    while outstanding:
        line = stdout.readline()
        if not line:
            break
        absorb(line, responses)
        outstanding -= responses.keys()
    stdin.close()
    for line in stdout.read().splitlines():
        absorb(line, responses)
    return responses


def _exchange(
    stdin: IO[str], stdout: IO[str], client_name: str
) -> dict[int, dict[str, object]]:
    """Send the fixed six-message contract batch and drain it (see
    `drain_exchange`)."""
    return drain_exchange(stdin, stdout, frames(client_name), expected_request_ids())


def run_client(case: ContractCase) -> dict[int, dict[str, object]]:
    """Spawn the server, exchange one batch as a conformant host, reap it.

    source: ADR-0759"""
    env = environment(
        case.data_root / case.client_name / case.profile,
        socks_proxy_regression=case.socks_proxy_regression,
        storage_selection=case.storage_selection,
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            case.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            env=env,
        )
        stdin, stdout = process.stdin, process.stdout
        if (
            stdin is None or stdout is None
        ):  # pragma: no cover - PIPE is requested above
            raise ContractError(f"{case.label}: server pipes were not created")
        watchdog = threading.Timer(case.timeout, process.kill)
        watchdog.start()
        try:
            responses = _exchange(stdin, stdout, case.client_name)
            returncode = process.wait()
        finally:
            watchdog.cancel()
            stdout.close()
        if returncode != 0:
            stderr_file.seek(0)
            raise ContractError(
                f"{case.label}: server exited {returncode}\n{stderr_file.read()}"
            )
    return responses
