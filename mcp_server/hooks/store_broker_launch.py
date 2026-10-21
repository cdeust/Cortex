"""Starting the store broker as a detached child, through the plugin launcher.

The broker loads the store's native dependencies, so it starts like every
other child that needs ``deps/``: through ``scripts/launcher.py`` when the
plugin ships it (issue #667), detached from the client that launched it
(``detached_spawn``, ADR-1102), with the bound listener and the lease
inherited on Unix (the capture worker's spawn, ADR-0486). Until its own log
is open, its output goes to an owner-only file next to its socket.

source: ADR-1112 decision 1
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mcp_server.hooks.launcher_command import child_command
from mcp_server.shared import detached_spawn


def launch_broker(
    module: str,
    arguments: list[str],
    environment: dict[str, str],
    fds: tuple[int, ...],
    output: Path,
) -> None:
    """Start ``module`` detached; ``fds`` are inherited (POSIX only); its
    stdout and stderr go to the owner-only file ``output``, which the client
    quotes if the broker dies before it answers."""
    options = detached_spawn.options()
    if fds:
        options = {**options, "pass_fds": fds}
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output, flags, 0o600)
    try:
        subprocess.Popen(
            child_command(module, *arguments),
            stdin=subprocess.DEVNULL,
            stdout=descriptor,
            stderr=descriptor,
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, **environment},
            **options,
        )
    finally:
        os.close(descriptor)
