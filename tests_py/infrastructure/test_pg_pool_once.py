"""One pool of each kind per store, however many threads use it first
(ADR-1112 acceptance A1).

A1 measured 12 to 16 interactive connections from one broker whose pool
allows 8: its 10 worker threads raced the lazy first use of
``interactive_pool``, each opening its own pool. No database is needed to
pin the rule: the pool factory is replaced by a slow counter.

source: ADR-1112 acceptance A1
"""

from __future__ import annotations

import threading
import time

import pytest

pg_store = pytest.importorskip("mcp_server.infrastructure.pg_store")


@pytest.mark.parametrize(
    ("attribute", "factory"),
    [
        ("interactive_pool", "_open_interactive_pool"),
        ("batch_pool", "_open_batch_pool"),
    ],
)
def test_concurrent_first_use_opens_one_pool(attribute, factory, monkeypatch):
    store = pg_store.PgMemoryStore.__new__(pg_store.PgMemoryStore)
    store._interactive_pool = None  # noqa: SLF001 — the state __init__ sets
    store._batch_pool = None  # noqa: SLF001
    store._pool_lock = threading.Lock()  # noqa: SLF001
    opened: list[object] = []

    def slow_open(self):
        time.sleep(0.05)  # source: the window the race needs
        pool = object()
        opened.append(pool)
        return pool

    monkeypatch.setattr(pg_store.PgMemoryStore, factory, slow_open)
    seen: list[object] = []
    workers = [
        threading.Thread(target=lambda: seen.append(getattr(store, attribute)))
        for _ in range(10)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert len(opened) == 1 and set(map(id, seen)) == {id(opened[0])}
