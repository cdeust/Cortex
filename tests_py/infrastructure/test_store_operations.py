"""Named store operations: marking, resolution by name, one unit of work.

source: ADR-1112
"""

from __future__ import annotations

from tests_py._store_call import mark_test_operation

from contextlib import contextmanager

import pytest

from mcp_server.infrastructure import store_operations as ops
from mcp_server.infrastructure.handler_operations import all_rules_including_inactive


def test_a_marked_operation_resolves_by_its_wire_name():
    name = ops.operation_name(all_rules_including_inactive)
    assert name == (
        "mcp_server.infrastructure.handler_operations:all_rules_including_inactive"
    )
    assert ops.resolve_operation(name) is all_rules_including_inactive


@pytest.mark.parametrize(
    "name",
    [
        "os:system",  # outside the allowed package
        "mcp_server.handlers.anchor:handler",  # outside infrastructure
        "mcp_server.infrastructure.handler_operations:_tags",  # not marked
        "mcp_server.infrastructure.handler_operations:json.loads",  # dotted
        "mcp_server.infrastructure.no_such_module:op",
        "mcp_server.infrastructure.handler_operations:",
    ],
)
def test_resolution_refuses_anything_but_a_marked_infrastructure_function(name):
    with pytest.raises(ops.UnknownOperationError):
        ops.resolve_operation(name)


def test_marking_outside_infrastructure_is_refused():
    def handler_side(conn):  # module is tests_py..., not mcp_server.infrastructure
        return conn

    with pytest.raises(ValueError, match="mcp_server.infrastructure"):
        ops.store_operation(handler_side)


class _Conn:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


class _Store(ops.StoreOperationsMixin):
    def __init__(self) -> None:
        self.conn = _Conn()
        self.pools: list[str] = []

    @contextmanager
    def acquire_interactive(self):
        self.pools.append("interactive")
        yield self.conn

    @contextmanager
    def acquire_batch(self):
        self.pools.append("batch")
        yield self.conn


def test_call_commits_after_the_operation_and_uses_the_named_pool():
    store = _Store()
    assert store.call(_ok) == 1
    assert store.conn.events == ["commit"]
    store.call_batch(_ok)
    assert store.pools == ["interactive", "batch"]


def test_call_rolls_back_a_failed_operation_and_reraises():
    store = _Store()
    with pytest.raises(RuntimeError, match="boom"):
        store.call(_boom)
    assert store.conn.events == ["rollback"]


def test_call_refuses_an_unmarked_function():
    store = _Store()
    with pytest.raises(ops.UnknownOperationError):
        store.call(lambda conn: 1)
    assert store.pools == []


def _ok(conn) -> int:
    return 1


def _boom(conn) -> int:
    raise RuntimeError("boom")


# Test-local operations: marked by hand, as the decorator refuses this module.
for _fn in (_ok, _boom):
    mark_test_operation(_fn)
