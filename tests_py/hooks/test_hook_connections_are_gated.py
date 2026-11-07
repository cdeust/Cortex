"""Every connection a hook opens is gated (review of PR #775, finding B1).

``auto_recall`` passed its own psycopg connection to ``emit_hook_receipt``,
whose ``insert_receipt_on_connection`` bound a session id taken from the
transcript path without redaction: the hook's connection was a plain
``psycopg.Connection``, outside the gate. Each hook connection below writes a
receipt whose session id carries a real-format fake key, and the stored row is
read back through an independent connection.

These hooks open PostgreSQL connections, so the test needs the psycopg
driver and a reachable server: on the SQLite leg (no [postgresql] extra) it
is skipped by capability. That the connections are gated by construction on
every install is pinned by ``tests_py/architecture/test_storage_redaction_gate.py``,
which runs on every leg.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.injection_receipts import emit_hook_receipt
from scripts.secret_corpus import sample
from tests_py.conftest import _TEST_DB_URL, _USE_PG  # type: ignore  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="the [postgresql] extra is absent")
pytestmark = pytest.mark.skipif(not _USE_PG, reason="PostgreSQL not reachable")

KEY = sample("github-pat").value


def _memory_id() -> int:
    with psycopg.connect(_TEST_DB_URL, autocommit=True) as raw:
        return raw.execute(
            "INSERT INTO memories (content, tags, domain) VALUES ('m', '[]', 'd') "
            "RETURNING id"
        ).fetchone()[0]


def _stored_session_ids() -> list[str]:
    with psycopg.connect(_TEST_DB_URL, autocommit=True) as raw:
        return [r[0] for r in raw.execute("SELECT session_id FROM injection_receipts")]


@pytest.mark.parametrize(
    ("module", "connect"),
    [
        ("mcp_server.hooks.auto_recall", "_connect"),
        ("mcp_server.hooks.session_start_db", "_connect_pg"),
        ("mcp_server.hooks.agent_briefing_query", "_connect"),
    ],
)
def test_a_hook_connection_redacts_what_it_writes(module, connect, monkeypatch):
    import importlib

    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    hook = importlib.import_module(module)
    monkeypatch.setattr(hook, "_DATABASE_URL", _TEST_DB_URL, raising=False)
    conn = getattr(hook, connect)()
    assert conn is not None
    try:
        receipt = emit_hook_receipt(
            conn,
            [{"memory_id": _memory_id()}],
            channel="auto_recall",
            session_id=f"transcript-{KEY}",
        )
    finally:
        conn.close()
    assert receipt is not None
    stored = _stored_session_ids()
    assert stored and all(KEY not in s for s in stored), stored
