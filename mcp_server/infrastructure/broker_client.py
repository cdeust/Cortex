"""The broker client: a store whose every call is one request to the broker.

``BrokerStore`` stands where ``PgMemoryStore`` stood in every client process
(MCP servers, hooks, background jobs). It holds no database connection:
allowlisted methods and marked operations travel as requests, streams are
sequences of stateless keyset-page requests, and the request class
(interactive or background) and deadline travel with each request. Each
thread uses its own broker channel, opened lazily and launched on demand.

Version skew (ADR-1112 decision 6): the broker announces the schema version
it serves. A client that needs a higher one asks that broker to drain and
exit, then launches its own; a client older than the broker's schema is
refused with "upgrade Cortex".

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from mcp_server.infrastructure.broker_errors import (
    BrokerUnavailableError,
    refusal_error,
    remote_error,
)
from mcp_server.infrastructure.broker_protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    dumps,
    loads,
)
from mcp_server.infrastructure.schema_versions import (
    SCHEMA_VERSION,
    SchemaTooNewError,
    code_revision,
)
from mcp_server.infrastructure.store_operations import (
    current_request_class,
    operation_name,
)

# source: ADR-1108 (a hook's 30 s budget) and ADR-0534 (the 30 min batch bound)
DEADLINES = {"interactive": 30.0, "background": 1800.0}

Connect = Callable[[float], Any]  # monotonic deadline -> connected channel


class BrokerClient:
    def __init__(
        self,
        connect: Connect,
        client_kind: str,
        diagnose: Callable[[], str] = lambda: "",
    ) -> None:
        self._connect = connect
        self._kind = client_kind
        self._diagnose = diagnose
        self._local = threading.local()
        self._ids = 0
        self._ids_lock = threading.Lock()
        self._open_channels: set[Any] = set()

    def _hello(self, channel: Any, deadline: float, drain: bool = False) -> dict:
        hello = {
            "t": "hello",
            "protocol": PROTOCOL_VERSION,
            "client": self._kind,
            "revision": code_revision(),
            "schema": SCHEMA_VERSION,
            "drain": drain,
        }
        channel.send_frame(dumps(hello), MAX_REQUEST_BYTES, deadline)
        return loads(channel.recv_frame(MAX_RESPONSE_BYTES, deadline))

    def _open(self, deadline: float) -> Any:
        channel = self._connect(deadline)
        welcome = self._hello(channel, deadline)
        if welcome.get("t") == "refused":
            channel.close()
            raise refusal_error(str(welcome.get("type")), str(welcome.get("error")))
        if welcome.get("t") != "welcome":
            channel.close()
            raise ProtocolError(f"unexpected handshake answer {welcome.get('t')!r}")
        served = int(welcome.get("schema", 0))
        if served > SCHEMA_VERSION:
            channel.close()
            raise SchemaTooNewError(
                f"the store broker serves schema version {served}, newer than "
                f"this Cortex (version {SCHEMA_VERSION}); upgrade Cortex."
            )
        if served < SCHEMA_VERSION:
            channel.close()
            self._drain(deadline)
            return self._open(deadline)
        self._local.broker_pid = welcome.get("pid")
        return channel

    def _drain(self, deadline: float) -> None:
        """Ask the older broker to exit once idle; the next connect launches
        a broker of this revision (the kernel lease admits one at a time)."""
        channel = self._connect(deadline)
        try:
            self._hello(channel, deadline, drain=True)
        finally:
            channel.close()
        while time.monotonic() < deadline:
            # source: ADR-1112 re-probe interval; the caller's deadline bounds it
            time.sleep(0.05)
            try:
                probe = self._connect(deadline)
                welcome = self._hello(probe, deadline)
                probe.close()
            except (OSError, ProtocolError):
                continue  # the old broker is closing; the next connect relaunches
            if int(welcome.get("schema", 0)) == SCHEMA_VERSION:
                return
        raise TimeoutError("the older store broker did not drain before the deadline")

    def _channel(self, deadline: float) -> Any:
        channel = getattr(self._local, "channel", None)
        if channel is None:
            channel = self._open(deadline)
            self._local.channel = channel
            with self._ids_lock:
                self._open_channels.add(channel)
        return channel

    def _discard(self) -> None:
        channel = getattr(self._local, "channel", None)
        self._local.channel = None
        if channel is not None:
            with self._ids_lock:
                self._open_channels.discard(channel)
            channel.close()

    def connect(self) -> None:
        """Open this thread's channel now, launching the broker if needed:
        a store that cannot be opened is reported where the store is made."""
        try:
            self._channel(time.monotonic() + DEADLINES["interactive"])
        except (OSError, ProtocolError, TimeoutError) as exc:
            raise BrokerUnavailableError(
                f"store broker: {type(exc).__name__}: {exc}{self._diagnose()}"
            ) from exc

    def request(self, kind: str, name: str, args: tuple, kwargs: dict, cls: str) -> Any:
        budget = DEADLINES[cls]
        deadline = time.monotonic() + budget
        with self._ids_lock:
            self._ids += 1
            request_id = self._ids
        message = {
            "t": "req",
            "id": request_id,
            "kind": kind,
            "name": name,
            "args": list(args),
            "kwargs": kwargs,
            "class": cls,
            "deadline": budget,
        }
        try:
            channel = self._channel(deadline)
            channel.send_frame(dumps(message), MAX_REQUEST_BYTES, deadline)
            reply = loads(channel.recv_frame(MAX_RESPONSE_BYTES, deadline))
        except (OSError, ProtocolError, TimeoutError) as exc:
            self._discard()
            raise BrokerUnavailableError(
                f"store broker: {type(exc).__name__}: {exc}{self._diagnose()}"
            ) from exc
        if reply.get("id") != request_id:
            self._discard()
            raise BrokerUnavailableError("store broker answered out of order")
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise remote_error(str(error.get("type")), str(error.get("message")))
        return reply.get("v")

    def broker_pid(self) -> int | None:
        """PID announced by the broker this thread is connected to."""
        return getattr(self._local, "broker_pid", None)

    def close(self) -> None:
        """Close every channel this client opened, from any thread."""
        self._local.channel = None
        with self._ids_lock:
            channels, self._open_channels = self._open_channels, set()
        for channel in channels:
            channel.close()


class BrokerStore:
    """The store interface, served by the broker (``backend == "postgresql"``)."""

    backend = "postgresql"
    has_vec = True

    def __init__(self, client: BrokerClient, methods: frozenset[str]) -> None:
        self._client = client
        self._methods = methods

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name not in self._methods:
            raise AttributeError(name)
        return functools.partial(self._method, name)

    def _method(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return self._client.request(
            "method", name, args, kwargs, current_request_class()
        )

    def call(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        pool: str | None = None,
        **kwargs: Any,
    ) -> Any:
        cls = "background" if pool == "batch" else current_request_class()
        return self._client.request("op", operation_name(fn), args, kwargs, cls)

    def call_batch(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return self.call(fn, *args, pool="batch", **kwargs)

    def iter_memories_for_decay(self, chunk_size: int = 1000) -> Iterator[list[dict]]:
        """Keyset pages, one request each; nothing stays open between them."""
        page, last_id = int(chunk_size), None
        while True:
            rows = self._method("_fetch_decay_page", page, last_id)
            if not rows:
                return
            yield rows
            if len(rows) < page:
                return
            last_id = rows[-1]["id"]

    def broker_pid(self) -> int | None:
        return self._client.broker_pid()

    def close(self) -> None:
        self._client.close()
