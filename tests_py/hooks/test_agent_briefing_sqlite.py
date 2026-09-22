"""Real SQLite briefing visibility and receipts. source: ADR-1085"""

from unittest.mock import patch

import pytest

from mcp_server.hooks import agent_briefing as hook
from mcp_server.hooks.agent_briefing_sqlite import SqliteBriefingConnection
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture
def connection(tmp_path):
    store = SqliteMemoryStore(db_path=str(tmp_path / "memory.db"))
    yield SqliteBriefingConnection(store)
    store.close()


def insert(connection, content="alpha task context", **values):
    return connection.store.insert_memory(
        {
            "content": content,
            "agent_context": "worker",
            "directory_context": "/project",
            "heat": 0.9,
            "heat_base": 0.9,
            **values,
        }
    )


def test_task_pass_and_promptless_team_pass_are_scoped(connection):
    prior = insert(connection)
    team = insert(connection, "team policy", is_team_decision=True)
    global_id = insert(
        connection,
        "global policy",
        is_team_decision=True,
        is_global=True,
        directory_context="/elsewhere",
    )
    for values in [
        {"directory_context": "/elsewhere"},
        {"directory_context": ""},
        {"is_benchmark": True},
        {"superseded_by_id": prior},
    ]:
        row = insert(connection, **values)
        if "superseded_by_id" in values:
            connection.store._conn.execute(
                "UPDATE memories SET superseded_by_id = ? WHERE id = ?", (prior, row)
            )
    task = hook._fetch_agent_context(connection, "worker", ["alpha"], "/project")
    assert [r["id"] for r in task] == [prior]
    team_rows = hook._fetch_agent_context(connection, "worker", [], "/project")
    assert {r["id"] for r in team_rows} == {team, global_id}
    assert {
        r["id"] for r in hook._fetch_agent_context(connection, "worker", [], None)
    } == {global_id}


@pytest.mark.parametrize("transcript", [None, "/sessions/child-transcript.jsonl"])
def test_native_start_records_exact_receipt(connection, capsys, transcript):
    memory = insert(connection, "shared decision", is_team_decision=True)
    with (
        patch.object(hook, "_connect", return_value=connection),
        pytest.raises(SystemExit),
    ):
        hook.process_event(
            {
                "hook_event_name": "SubagentStart",
                "agent_type": "worker",
                "cwd": "/project",
                "session_id": "child-test",
                "transcript_path": transcript,
            }
        )
    assert "shared decision" in capsys.readouterr().out
    rows = connection.store._conn.execute(
        "SELECT * FROM injection_receipt_items"
    ).fetchall()
    assert [r["memory_id"] for r in rows] == [memory]
    receipt = connection.store._conn.execute(
        "SELECT * FROM injection_receipts"
    ).fetchone()
    assert receipt["session_id"] == ("child-transcript" if transcript else "child-test")


def test_sqlite_selection_does_not_probe_postgres(connection, monkeypatch):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    with patch(
        "mcp_server.infrastructure.memory_store.get_shared_store",
        return_value=connection.store,
    ):
        result = hook._connect()
    assert isinstance(result, SqliteBriefingConnection)


def test_fts_operators_are_data(connection):
    insert(connection)
    assert (
        hook._fetch_agent_context(connection, "worker", ['alpha" OR "task'], "/project")
        == []
    )


def test_promptless_start_includes_scoped_role_prior(connection, capsys):
    memory = insert(connection, "native role context")
    with (
        patch.object(hook, "_connect", return_value=connection),
        pytest.raises(SystemExit),
    ):
        hook.process_event(
            {
                "hook_event_name": "SubagentStart",
                "agent_type": "worker",
                "cwd": "/project",
            }
        )
    output = capsys.readouterr().out
    assert "native role context" in output
    assert "role-prior" in output
    rows = connection.store._conn.execute(
        "SELECT memory_id FROM injection_receipt_items"
    ).fetchall()
    assert [r["memory_id"] for r in rows] == [memory]


def test_role_context_keeps_team_first_and_excludes_invalid_rows(connection):
    from mcp_server.hooks.agent_briefing_role import fetch_role_context

    own = insert(connection, "own role")
    for values in [
        {"directory_context": "/foreign"},
        {"is_benchmark": True},
        {"directory_context": ""},
        {"agent_context": "other"},
    ]:
        insert(connection, "excluded role", **values)
    old = insert(connection, "superseded")
    connection.store._conn.execute(
        "UPDATE memories SET superseded_by_id = ? WHERE id = ?", (own, old)
    )
    team = insert(
        connection, "team policy", agent_context="other", is_team_decision=True
    )
    global_id = insert(
        connection, "global role", directory_context="/foreign", is_global=True
    )
    rows = fetch_role_context(connection, "worker", "/project")
    assert rows[0]["id"] == team
    assert {r["id"] for r in rows} == {own, team, global_id}
    assert {r["id"] for r in fetch_role_context(connection, "worker", None)} == {
        global_id
    }


def test_full_team_budget_never_spends_a_slot_on_role_prior(connection):
    from mcp_server.hooks.agent_briefing_role import fetch_role_context

    for value in range(hook._MAX_MEMORIES):
        insert(connection, f"team {value}", is_team_decision=True)
    insert(connection, "role memory", heat_base=1.0)
    rows = fetch_role_context(connection, "worker", "/project")
    assert len(rows) == hook._MAX_MEMORIES
    assert all(row["source"] == "team" for row in rows)
