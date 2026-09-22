"""Real PostgreSQL child briefing paths. source: ADR-1085"""

import json

import pytest

from mcp_server.hooks import agent_briefing as hook
from tests_py.conftest import _TEST_DB_URL, _USE_PG

pytestmark = pytest.mark.skipif(not _USE_PG, reason="PostgreSQL test database required")


@pytest.fixture
def seeded_store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore(database_url=_TEST_DB_URL)

    def insert(content, **values):
        return store.insert_memory(
            {
                "content": content,
                "agent_context": "worker",
                "directory_context": "/project",
                "heat": 0.9,
                **values,
            }
        )

    prior = insert("orchid latency")
    team = insert("project policy", is_team_decision=True)
    insert("foreign policy", directory_context="/foreign", is_team_decision=True)
    insert("foreign role", directory_context="/foreign")
    insert("benchmark role", is_benchmark=True)
    insert("other role", agent_context="other")
    old = insert("superseded role")
    store._conn.execute(
        "UPDATE memories SET superseded_by_id = %s WHERE id = %s", (prior, old)
    )
    yield store, prior, team
    store.close()


def test_native_postgres_team_start_and_task_rewrite(seeded_store, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    store, prior, team = seeded_store
    events = [
        {"hook_event_name": "SubagentStart", "agent_type": "worker", "cwd": "/project"},
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {"message": "orchid latency", "agent_type": "worker"},
            "cwd": "/project",
        },
    ]
    for event in events:
        with pytest.raises(SystemExit):
            hook.process_event(event)
    output = capsys.readouterr().out
    assert "foreign policy" not in output
    contexts = [json.loads(line)["hookSpecificOutput"] for line in output.splitlines()]
    assert "project policy" in contexts[0]["additionalContext"]
    assert "orchid latency" in contexts[1]["updatedInput"]["message"]
    rows = store._conn.execute(
        "SELECT memory_id FROM injection_receipt_items ORDER BY receipt_id, rank"
    ).fetchall()
    assert [row["memory_id"] for row in rows] == [team, prior, prior]
