"""Real PostgreSQL transactions for scope repair. source: ADR-1083"""

import os
import uuid

import pytest

from scripts.reclassify_team_scope_db import ScopeDatabase

psycopg = pytest.importorskip("psycopg")
sql = psycopg.sql
make_conninfo = psycopg.conninfo.make_conninfo


@pytest.fixture
def scope_pg_url():
    url = os.environ.get("CORTEX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicitly configured scratch CORTEX_TEST_DATABASE_URL")
    schema = "scope_611_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield make_conninfo(url, options=f"-csearch_path={schema},public")
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def seed(url, marker=True):
    with psycopg.connect(url) as conn:
        marker_sql = (
            ", is_team_decision BOOLEAN NOT NULL DEFAULT FALSE" if marker else ""
        )
        conn.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, "
            "tags JSONB, domain TEXT, directory_context TEXT, "
            "agent_context TEXT, is_global BOOLEAN, is_benchmark BOOLEAN"
            + marker_sql
            + ")"
        )
        conn.execute("CREATE VIEW current_memories AS SELECT * FROM memories")
        conn.execute(
            "INSERT INTO memories (id, content, tags, domain, "
            "directory_context, agent_context, is_global, is_benchmark) "
            "VALUES (1, 'DECISION: parser', '[]', 'a', '/a', 'agent', TRUE, FALSE)"
        )


def change(identifier=1):
    return {
        "id": identifier,
        "directory_context": "/a",
        "is_global": False,
        "is_team_decision": True,
    }


def test_pg_apply_second_run_and_persisted_marker(scope_pg_url):
    seed(scope_pg_url)
    with ScopeDatabase(scope_pg_url, None) as db:
        rows = db.fetch_rows(require_marker=True)
        assert len(rows) == 1
        assert rows[0]["tags"] == []
        db.apply_changes([change()])
    with ScopeDatabase(scope_pg_url, None) as db:
        assert db.fetch_rows(require_marker=True) == []
        db.apply_changes([])
    with psycopg.connect(scope_pg_url) as conn:
        assert conn.execute(
            "SELECT is_global,is_team_decision FROM memories"
        ).fetchone() == (False, True)


def test_pg_later_update_failure_rolls_back(scope_pg_url):
    seed(scope_pg_url)
    with pytest.raises(RuntimeError, match="exactly row"):
        with ScopeDatabase(scope_pg_url, None) as db:
            db.fetch_rows(require_marker=True)
            db.apply_changes([change(), change(99)])
    with psycopg.connect(scope_pg_url) as conn:
        assert conn.execute(
            "SELECT is_global,is_team_decision FROM memories"
        ).fetchone() == (True, False)


def test_pg_old_schema_read_only_and_apply_refusal(scope_pg_url):
    seed(scope_pg_url, marker=False)
    with ScopeDatabase(scope_pg_url, None) as db:
        assert db.fetch_rows(require_marker=False)[0]["is_team_decision"] is False
        with pytest.raises(ValueError, match="schema migration"):
            db.fetch_rows(require_marker=True)
