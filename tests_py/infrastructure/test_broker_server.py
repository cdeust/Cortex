"""The broker server and client over connected stream sockets, no database
(ADR-1112 increment 3): handshake, dispatch through the executor's allowlist,
remote errors, malformed and oversized frames, drain on version skew.

source: ADR-1112
"""

from __future__ import annotations

import queue
import socket
import sys
import threading
import time

import pytest

from mcp_server.infrastructure import broker_protocol as protocol
from mcp_server.infrastructure.broker_client import BrokerClient, BrokerStore
from mcp_server.infrastructure.broker_errors import BrokerRemoteError
from mcp_server.infrastructure.broker_executor import StoreExecutor
from mcp_server.infrastructure.broker_scheduler import SchedulerPolicy
from mcp_server.infrastructure.broker_server import (
    BrokerServer,
    Identity,
    ServerPolicy,
)
from mcp_server.infrastructure.broker_unix import SocketChannel
from mcp_server.infrastructure.schema_versions import SCHEMA_VERSION, SchemaTooNewError
from mcp_server.infrastructure.store_operations import StoreOperationsMixin

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="socketpair transport")


class _FakeStore(StoreOperationsMixin):
    backend = "postgresql"

    def __init__(self) -> None:
        self.seen: list[tuple] = []

    def get_memory(self, memory_id: int) -> dict:
        self.seen.append(("get_memory", memory_id))
        return {"id": memory_id}

    def fail(self) -> None:
        raise LookupError("no such memory")

    def acquire_interactive(self):  # in-process only: never exposed
        raise AssertionError("must not be reachable through the broker")

    def _secret(self) -> None:
        raise AssertionError("private methods are not exposed")


class _Harness:
    def __init__(self, schema: int = SCHEMA_VERSION) -> None:
        self.pending: queue.Queue = queue.Queue()
        self.store = _FakeStore()
        policy = ServerPolicy(
            SchedulerPolicy(interactive_slots=1, background_slots=1, queue_limit=8),
            idle_seconds=60.0,
            max_connections=4,
        )
        self.server = BrokerServer(
            self._accept, StoreExecutor(self.store), policy, Identity("test", schema)
        )
        self.thread = threading.Thread(
            target=self.server.run, args=(lambda: None,), daemon=True
        )
        self.thread.start()

    def _accept(self):
        try:
            return self.pending.get(timeout=0.1)
        except queue.Empty:
            return None

    def connect(self, deadline: float) -> SocketChannel:
        server_side, client_side = socket.socketpair()
        self.pending.put(SocketChannel(server_side))
        return SocketChannel(client_side)

    def store_client(self) -> BrokerStore:
        client = BrokerClient(self.connect, "test")
        return BrokerStore(client, StoreExecutor(self.store).methods)

    def close(self) -> None:
        self.server.stop()
        self.thread.join(timeout=5)


@pytest.fixture
def harness():
    h = _Harness()
    yield h
    h.close()


def test_a_method_call_round_trips_through_the_broker(harness):
    store = harness.store_client()
    assert store.get_memory(7) == {"id": 7}
    assert harness.store.seen == [("get_memory", 7)]


def test_in_process_and_private_members_are_not_exposed(harness):
    store = harness.store_client()
    for name in ("acquire_interactive", "_secret", "close_everything"):
        with pytest.raises(AttributeError):
            getattr(store, name)


def test_a_remote_failure_is_reported_with_its_type(harness):
    """A built-in exception type crosses back as itself, so callers that
    catch it keep working; anything else is a BrokerRemoteError."""
    store = harness.store_client()
    with pytest.raises(LookupError, match="no such memory"):
        store.fail()


def test_the_executor_refuses_names_outside_the_allowlist(harness):
    client = BrokerClient(harness.connect, "test")
    with pytest.raises(BrokerRemoteError, match="UnknownOperationError"):
        client.request("method", "acquire_interactive", (), {}, "interactive")
    with pytest.raises(BrokerRemoteError, match="UnknownOperationError"):
        client.request("op", "os:system", ("true",), {}, "interactive")


def _raw(harness) -> SocketChannel:
    channel = harness.connect(time.monotonic() + 5)
    hello = {"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "client": "raw"}
    channel.send_frame(protocol.dumps(hello), protocol.MAX_REQUEST_BYTES, None)
    assert (
        protocol.loads(channel.recv_frame(1 << 20, time.monotonic() + 5))["t"]
        == "welcome"
    )
    return channel


def _closed(channel: SocketChannel) -> bool:
    try:
        channel.recv_frame(1 << 20, time.monotonic() + 5)
    except ConnectionError:
        return True
    return False


def test_a_malformed_frame_closes_the_connection_and_the_broker_lives_on(harness):
    channel = _raw(harness)
    channel.sock.sendall(protocol.frame(b"{not json", 100))
    assert _closed(channel)
    assert harness.store_client().get_memory(1) == {"id": 1}


def test_an_oversized_frame_header_closes_the_connection(harness):
    channel = _raw(harness)
    channel.sock.sendall((protocol.MAX_REQUEST_BYTES + 1).to_bytes(4, "big"))
    assert _closed(channel)


def test_a_wrong_protocol_version_is_refused():
    h = _Harness()
    try:
        channel = h.connect(time.monotonic() + 5)
        channel.send_frame(
            protocol.dumps({"t": "hello", "protocol": 999}), 1 << 20, None
        )
        assert (
            protocol.loads(channel.recv_frame(1 << 20, time.monotonic() + 5))["t"]
            == "refused"
        )
        assert _closed(channel)
    finally:
        h.close()


def test_a_broker_on_a_newer_schema_is_refused_by_the_client():
    h = _Harness(schema=SCHEMA_VERSION + 1)
    try:
        with pytest.raises(Exception) as caught:
            h.store_client().get_memory(1)
        assert isinstance(caught.value.__cause__ or caught.value, SchemaTooNewError)
    finally:
        h.close()


def test_connections_beyond_the_cap_are_closed_unread(harness):
    channels = [_raw(harness) for _ in range(4)]
    extra = harness.connect(time.monotonic() + 5)
    assert _closed(extra)
    for channel in channels:
        channel.close()
