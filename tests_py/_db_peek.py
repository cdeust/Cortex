"""The connection a test uses to seed or read rows behind the store.

In process (the suite's default) that is the store's own persistent
connection, as the tests always used. Through the broker
(``CORTEX_TEST_BROKER_MODE=1``) the client store has no connection by design
(ADR-1112), so the test gets one direct connection to the same database, in
the same mode (autocommit, dict rows). Test-side only: production code never
holds a connection outside the broker.

source: ADR-1112 increment 5
"""

from __future__ import annotations

import atexit
import os
from typing import Any

_direct: dict[str, Any] = {}


def store_connection(store: Any) -> Any:
    try:
        return store._conn  # noqa: SLF001 — the in-process store's own connection
    except AttributeError:
        pass
    url = os.environ["DATABASE_URL"]
    conn = _direct.get(url)
    if conn is None or conn.closed:
        import psycopg  # noqa: PLC0415 — PG-only path
        from psycopg.rows import dict_row  # noqa: PLC0415

        conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        _direct[url] = conn
        atexit.register(conn.close)
    return conn
