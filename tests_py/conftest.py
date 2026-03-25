"""Global test configuration — ensures PG connections recover from failed transactions."""

import pytest


@pytest.fixture(autouse=True)
def _pg_transaction_recovery():
    """Roll back any poisoned PG transactions between tests.

    When a test fails mid-transaction, psycopg leaves the connection in
    InFailedSqlTransaction state. This fixture ensures subsequent tests
    start with a clean connection by rolling back after each test.
    """
    yield
    # After each test, reset any module-level store singletons that may
    # have a poisoned connection
    try:
        import mcp_server.handlers.recall as recall_mod
        import mcp_server.handlers.remember as remember_mod

        for mod in [recall_mod, remember_mod]:
            store = getattr(mod, "_store", None)
            if store is not None and hasattr(store, "_conn"):
                try:
                    store._conn.rollback()
                except Exception:
                    pass
    except ImportError:
        pass
