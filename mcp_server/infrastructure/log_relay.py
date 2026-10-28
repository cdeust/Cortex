"""Child-process output reaches its log only through the redaction gate.

A detached child (consolidation, re-analysis) used to inherit an open log
file as its stdout/stderr, writing raw bytes no parent could filter. Now the
spawner starts a relay process first and hands the child the relay's stdin:
the relay reads the child's output (and that of any grandchild inheriting
the descriptor), redacts it block by block and appends it to the log with
``gated_files.append_text``. It exits at end of input, when the last writer
closes the pipe.

Lines are grouped into blocks (a pause in output, or a size cap) so a
multi-line secret such as a PEM block is redacted whole; an opened
``-----BEGIN`` is held until its ``-----END`` line or the cap.

Run as ``python -m mcp_server.infrastructure.log_relay <log path>``; it
imports only ``mcp_server.shared`` (stdlib), so ``PYTHONPATH`` pointing at
the package root is all it needs, whatever launcher started the parent.

source: ADR-1110"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_server.shared.gated_files import append_text
from mcp_server.shared.platform import python_executable

# source: ADR-1110 — output pause that closes a block (seconds) and the
# block size cap (lines); a PEM key is ~30 lines, so 400 holds any one key.
_BLOCK_PAUSE_S = 0.2  # source: ADR-1110
_BLOCK_MAX_LINES = 400  # source: ADR-1110 (a PEM key is about 30 lines)
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def relay_command(log_path: Path, mode: int | None = None) -> list[str]:
    command = [python_executable(), "-m", "mcp_server.infrastructure.log_relay"]
    return [*command, str(log_path), *([] if mode is None else [oct(mode)])]


def _relay_env(base: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    parts = [str(_PACKAGE_ROOT), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(p for p in parts if p)
    return env


@dataclass(frozen=True)
class LoggedSpawn:
    """The started child and the relay that owns its output."""

    child: subprocess.Popen
    relay: subprocess.Popen


def spawn_logged(
    cmd: list[str],
    log_path: Path,
    *,
    mode: int | None = None,
    env: dict[str, str] | None = None,
    **popen_kwargs: Any,
) -> LoggedSpawn:
    """Start ``cmd`` with stdout+stderr piped through a relay into ``log_path``.

    ``popen_kwargs`` (detach flags, ``cwd``) apply to both processes, so the
    relay outlives the spawner exactly as long as the child does. ``mode``
    is applied to the log file on every append (owner-only logs)."""
    relay = subprocess.Popen(  # noqa: S603 — fixed module of this package
        relay_command(log_path, mode),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_relay_env(env),
        **popen_kwargs,
    )
    assert relay.stdin is not None  # stdin=PIPE
    try:
        child = subprocess.Popen(  # noqa: S603 — caller-built trusted command
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=relay.stdin,
            stderr=subprocess.STDOUT,
            env=env,
            **popen_kwargs,
        )
    finally:
        relay.stdin.close()
    return LoggedSpawn(child=child, relay=relay)


def _reader(stream: Any, lines: "queue.Queue[str | None]") -> None:
    for raw in iter(stream.readline, b""):
        lines.put(raw.decode("utf-8", "replace"))
    lines.put(None)


def _holds_open_key(block: list[str]) -> bool:
    text = "".join(block)
    return text.rfind("-----BEGIN") > text.rfind("-----END")


def relay(stream: Any, log_path: Path, mode: int | None = None) -> None:
    """Copy ``stream`` (binary) into ``log_path`` block by block, redacted."""
    lines: "queue.Queue[str | None]" = queue.Queue()
    threading.Thread(target=_reader, args=(stream, lines), daemon=True).start()
    block: list[str] = []
    done = False
    while not done:
        try:
            line = lines.get(timeout=_BLOCK_PAUSE_S)
        except queue.Empty:
            line = ""
        if line is None:
            done = True
        elif line:
            block.append(line)
            if len(block) < _BLOCK_MAX_LINES:
                continue
        if block and (
            done or len(block) >= _BLOCK_MAX_LINES or not _holds_open_key(block)
        ):
            append_text(log_path, "".join(block), mode=mode)
            block = []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = int(args[1], 8) if len(args) > 1 else None
    relay(sys.stdin.buffer, Path(args[0]), mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
