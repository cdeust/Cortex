"""Where a client finds its store broker, and how it launches one.

One broker per resolved store: the key is a digest of the database URL, so
two stores on one machine get two brokers and one store never gets two. On
Unix the broker's private directory is ``<Cortex root>/.store-broker/<key>``
(0700, socket 0600, peer UID checked, ``broker_unix``); on Windows the
endpoint is a named pipe restricted to the user's SID (``broker_pipe``).

The URL travels to the spawned broker in its environment
(``CORTEX_BROKER_DATABASE_URL``), never on its command line, where any
local user could read it in the process table (ADR-1112, threat model,
information disclosure).

The launch itself needs the plugin launcher (deps isolation, issue #667),
which lives in ``hooks``; it is injected by the composition root
(``hooks.wiring``) through ``configure_broker_launcher``.

source: ADR-1112 decisions 1, 2 and owner decision 2
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.broker_client import BrokerClient, BrokerStore
from mcp_server.infrastructure.broker_errors import BrokerLaunchError

# source: ADR-1112 the child reads its store from here, not from argv
URL_ENVIRONMENT = "CORTEX_BROKER_DATABASE_URL"
# source: ADR-1112 decision 1: set in the broker process (it holds the store
# itself) and by the test harness; every other process talks to the broker
IN_PROCESS_ENVIRONMENT = "CORTEX_STORE_IN_PROCESS"
# source: ADR-1112 the broker's stdout and stderr until its own log is open
OUTPUT_NAME = "broker.out"
# source: ADR-1112 hex digits of the store key (64 bits: no collision in practice)
_KEY_LENGTH = 16

# source: ADR-1112 bytes of the broker's start-up output shown to the client
_DIAGNOSIS_BYTES = 2000

# (module, arguments, environment additions, inherited fds, output file)
Launcher = Callable[[str, list[str], dict[str, str], tuple[int, ...], Path], None]
_launcher: Launcher | None = None


def configure_broker_launcher(launcher: Launcher) -> None:
    global _launcher
    _launcher = launcher


def store_key(database_url: str, root: Path) -> str:
    """One broker per resolved store: the database URL and the Cortex root
    (ADR-1112 decision 1)."""
    material = f"{database_url}|{root.expanduser().absolute()}".encode()
    return hashlib.sha256(material).hexdigest()[:_KEY_LENGTH]


def _diagnosis(output: Path) -> str:
    """The end of a broker's start-up output: why it died before answering."""
    try:
        with output.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - _DIAGNOSIS_BYTES))
            tail = stream.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""
    return f"; broker output ({output}): {tail}" if tail else ""


def _launch(arguments: list[str], url: str, fds: tuple[int, ...], output: Path) -> None:
    if _launcher is None:
        raise BrokerLaunchError(
            "no store broker launcher configured; the process entry point must "
            "call hooks.wiring.wire_composition_root()"
        )
    environment = {URL_ENVIRONMENT: url, IN_PROCESS_ENVIRONMENT: "1"}
    _launcher("mcp_server.hooks.store_broker", arguments, environment, fds, output)


def _unix_connect(root: Path, url: str) -> tuple[Callable[[float], Any], Path]:
    from mcp_server.infrastructure import broker_unix  # noqa: PLC0415 — Unix transport only

    key = store_key(url, root)
    base = broker_unix.socket_root(root, key)
    output = base / broker_unix.RUNTIME_NAME / key / OUTPUT_NAME

    def spawn(listener: Any, lease: int) -> None:
        arguments = ["--listener-fd", str(listener.fileno()), "--lease-fd", str(lease)]
        _launch(arguments, url, (listener.fileno(), lease), output)

    def connect(deadline: float) -> Any:
        return broker_unix.connect_or_spawn(base, key, deadline, spawn)

    return connect, output


def _pipe_connect(root: Path, url: str) -> tuple[Callable[[float], Any], Path]:
    from mcp_server.infrastructure import broker_pipe  # noqa: PLC0415 — Windows transport only

    key = store_key(url, root)
    name = broker_pipe.pipe_name(key)
    output = root / ".store-broker" / f"{key}.{OUTPUT_NAME}"

    def connect(deadline: float) -> Any:
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return broker_pipe.connect_or_spawn(
            name, deadline, lambda: _launch(["--pipe-name", name], url, (), output)
        )

    return connect, output


def broker_store(database_url: str, root: Path, client_kind: str) -> BrokerStore:
    """A store for ``database_url`` served by its broker (launched on demand)."""
    from mcp_server.infrastructure.broker_executor import allowed_methods  # noqa: PLC0415 — needs the PG store class
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — same

    if sys.platform == "win32":
        connect, output = _pipe_connect(root, database_url)
    else:
        connect, output = _unix_connect(root, database_url)
    client = BrokerClient(connect, client_kind, lambda: _diagnosis(output))
    client.connect()  # launch now: a store that cannot open is reported here
    return BrokerStore(client, allowed_methods(PgMemoryStore))


def store_in_process() -> bool:
    """True in the broker itself and under the test harness's default."""
    return os.environ.get(IN_PROCESS_ENVIRONMENT) == "1"
