"""A throwaway PostgreSQL cluster with its own ``max_connections``.

The shared test server cannot be saturated without saturating every other
client of that server (the owner's live store included), and the test role
is a superuser there, so ``ALTER DATABASE ... CONNECTION LIMIT`` does not
bind it. A private cluster from the same binaries (``initdb``/``pg_ctl`` on
PATH, pgvector in their share directory) is the only place a test may drive
``FATAL: sorry, too many clients already`` for real. TCP on 127.0.0.1 only,
no Unix socket (a pytest tmp path can exceed the 103-byte socket limit).

source: ADR-1112
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def available() -> bool:
    return shutil.which("initdb") is not None and shutil.which("pg_ctl") is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def private_cluster(root: Path, max_connections: int, extra: str = "") -> Iterator[str]:
    """Yield the maintenance URL of a running private cluster; stop it on exit.

    ``extra`` appends server options (``-c name=value``), e.g. statement
    logging for an experiment. Post: the postmaster is stopped
    (``-m immediate``) whatever the body did.
    """
    data = root / "data"
    subprocess.run(
        ["initdb", "-D", str(data), "-A", "trust", "-E", "UTF8", "--no-locale"],
        check=True,
        capture_output=True,
    )
    port = _free_port()
    options = (
        f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories='' "
        f"-c max_connections={max_connections} -c fsync=off {extra}"
    )
    subprocess.run(
        [
            "pg_ctl",
            "-D",
            str(data),
            "-o",
            options,
            "-l",
            str(root / "pg.log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"postgresql://127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            ["pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=False,
            capture_output=True,
        )
