"""PR #826: automatic injection rejects untrusted provenance on both stores."""

import sqlite3

import pytest

from mcp_server.handlers.memory_import_checks import checked_records
from mcp_server.handlers.recall_helpers import _trigger_result
from mcp_server.hooks import auto_recall
from mcp_server.infrastructure.hook_capture_filter import HOOK_CAPTURE_FILTER


@pytest.mark.parametrize("origin", [
    "deliberate", "legacy", "network", "local_action", "unknown", "future", "", None,
])
@pytest.mark.parametrize("source", ["", None, "post_tool_capture"])
def test_hook_sql_trust_policy(origin, source):
    expected = origin == "deliberate" or (
        origin == "legacy" and source != "post_tool_capture"
    )
    with sqlite3.connect(":memory:") as conn:
        actual = conn.execute(
            f"SELECT {HOOK_CAPTURE_FILTER} FROM "
            "(SELECT ? AS capture_origin, ? AS source) m",
            (origin, source),
        ).fetchone()[0]
    assert bool(actual) is expected


def test_postgres_pools_share_the_pre_limit_trust_predicate(monkeypatch):
    statements = []

    class Connection:
        def execute(self, statement, params):
            statements.append(statement)
            return self

        def fetchall(self):
            return []

    def rank(query, lexical, hot_pool):
        hot_pool()
        return lexical

    monkeypatch.setattr(auto_recall, "rank_memories", rank)
    assert auto_recall._recall_memories(Connection(), "espresso beans", "/repo") == []
    assert len(statements) == 2
    for sql in statements:
        assert HOOK_CAPTURE_FILTER in sql
        assert sql.index(HOOK_CAPTURE_FILTER) < sql.index("LIMIT")


def test_sqlite_lexical_prefix_is_bounded_and_semantic_query_is_full(monkeypatch):
    query = "espresso beans ".ljust(auto_recall._MAX_LEXICAL_QUERY_CHARS)
    query += "extra words"
    inputs = []
    queries = []

    class Store:
        def search_fts(self, value, **kwargs):
            inputs.append(value)
            return []

    def rank(full_query, lexical, hot_pool):
        queries.append(full_query)
        return []

    monkeypatch.setattr(auto_recall, "rank_memories", rank)
    assert auto_recall._recall_memories_sqlite(Store(), query, "/repo") == []
    assert inputs == [auto_recall._fts_query_from_prompt(
        query[:auto_recall._MAX_LEXICAL_QUERY_CHARS]
    )]
    assert queries == [query]


@pytest.mark.parametrize("trust", [False, True])
def test_import_provenance_requires_explicit_trust(trust):
    fields = ("content", "tags", "directory_context", "capture_origin", "source")
    header = {"project_root": "/repo", "include_global": False, "fields": list(fields)}
    record = {
        "content": "imported instructions", "tags": [], "directory_context": "/repo",
        "capture_origin": "deliberate", "source": "post_tool_capture",
    }
    result = checked_records(
        header, [record], fields, into_project_root=None, trust_flags=trust
    )
    assert result[0]["capture_origin"] == ("deliberate" if trust else "unknown")
    assert record["capture_origin"] == "deliberate"


def test_trigger_result_does_not_invent_trusted_provenance():
    assert _trigger_result(1, {"content": "old row"})["capture_origin"] == "unknown"
