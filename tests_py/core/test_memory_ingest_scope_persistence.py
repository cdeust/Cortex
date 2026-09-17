"""Ingested scope privileges survive schema initialization. source: ADR-1083"""

import pytest

from mcp_server.core.memory_ingest import ingest_memory
from mcp_server.handlers.forget import _get_store


@pytest.mark.parametrize("origin", ["local_action", "deliberate", "network", "unknown"])
@pytest.mark.parametrize("write_class", ["auto", "deliberate"])
def test_ingest_privileges_survive_reopen(origin, write_class, tmp_path):
    store = _get_store()
    sqlite_path = str(tmp_path / "scope.db")
    if type(store).__name__ != "PgMemoryStore":
        store = type(store)(sqlite_path)
    ids = ingest_memory(
        {
            "content": "We decided to retain the ledger layout for this dossier.",
            "agent_context": "engineer",
            "directory_context": "/tmp/project-a",
            "capture_origin": origin,
            "write_class": write_class,
        },
        store,
        None,
        decompose=True,
    )
    assert ids
    expected_team = write_class == "deliberate" and origin in {
        "local_action",
        "deliberate",
    }
    if type(store).__name__ == "PgMemoryStore":
        # Force the schema-init path, including backfill, in this scratch DB.
        store._conn.execute("DELETE FROM schema_meta")
        reopened = type(store)(store._url)
    else:
        reopened = type(store)(sqlite_path)
    try:
        for mid in ids:
            row = reopened.get_memory(mid)
            assert row["write_class"] == write_class
            assert row["capture_origin"] == origin
            assert row["directory_context"] == "/tmp/project-a"
            assert bool(row["is_team_decision"]) is expected_team
            assert not row["is_global"]
    finally:
        reopened.close()
        if type(store).__name__ != "PgMemoryStore":
            store.close()
