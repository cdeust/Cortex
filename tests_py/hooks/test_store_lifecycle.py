"""Unit tests for the close_shared_store_on_exit context manager (issue #398).

Covers the three exit paths a one-shot hook process actually takes: normal
return, a raised exception, and sys.exit() (SystemExit) — the pattern every
hook in mcp_server/hooks/*.py wraps its main() call in.
"""

from __future__ import annotations

import pytest

from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit


def test_closes_store_on_normal_completion(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.reset_shared_store",
        lambda: calls.append(True),
    )
    with close_shared_store_on_exit():
        pass
    assert calls == [True]


def test_closes_store_when_block_raises(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.reset_shared_store",
        lambda: calls.append(True),
    )
    with pytest.raises(ValueError):
        with close_shared_store_on_exit():
            raise ValueError("boom")
    assert calls == [True]


def test_closes_store_on_sys_exit(monkeypatch):
    """The exact shape every hook's __main__ block relies on: main() calls
    sys.exit(...), and the store must still be closed before the process
    actually ends (issue #398)."""
    calls: list[bool] = []
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.reset_shared_store",
        lambda: calls.append(True),
    )
    with pytest.raises(SystemExit) as excinfo:
        with close_shared_store_on_exit():
            raise SystemExit(0)
    assert excinfo.value.code == 0
    assert calls == [True]


def test_teardown_failure_does_not_mask_block_exception(monkeypatch):
    """A broken reset_shared_store() must never hide the wrapped block's
    own exception -- teardown is best-effort, never load-bearing for the
    caller's control flow."""

    def _raise():
        raise RuntimeError("pool close failed")

    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.reset_shared_store", _raise
    )
    with pytest.raises(ValueError, match="original"):
        with close_shared_store_on_exit():
            raise ValueError("original")


def test_teardown_failure_is_swallowed_on_success_path(monkeypatch):
    """A broken reset_shared_store() on an otherwise-successful block must
    not raise past the context manager -- the hook's own outcome (the
    stamp write, the exit code) is not teardown's to break."""

    def _raise():
        raise RuntimeError("pool close failed")

    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.reset_shared_store", _raise
    )
    with close_shared_store_on_exit():
        pass  # no exception -- teardown's own failure must not propagate
