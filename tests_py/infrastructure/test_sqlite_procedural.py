"""Procedural skills survive a session end on the default backend (#596).

`procedural_skills` existed only on PostgreSQL, so on SQLite the session-end
writer mined its skills and lost every one of them to an `AttributeError` its
caller swallowed. These tests hold the table and its two operations on the
backend most installs run.

source: ADR-1075
"""

from __future__ import annotations

import pytest

SKILL = {
    "skill_id": "bash-read",
    "action_sequence": "Bash>Read",
    "context_signature": "eng",
    "occurrences": 4,
    "success_count": 3,
    "failure_count": 1,
    "proficiency": 0.7,
    "is_habitual": True,
}


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import (
        get_shared_store,
        reset_shared_store,
    )

    db = tmp_path / "memory.db"
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(db))
    monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(db))
    get_memory_settings.cache_clear()
    reset_shared_store()

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    yield store

    reset_shared_store()
    get_memory_settings.cache_clear()


def test_the_default_backend_has_the_operations(sqlite_store) -> None:
    assert hasattr(sqlite_store, "upsert_procedural_skill")
    assert hasattr(sqlite_store, "get_procedural_skills")


def test_a_skill_round_trips(sqlite_store) -> None:
    row_id = sqlite_store.upsert_procedural_skill(SKILL)

    stored = sqlite_store.get_procedural_skills(0.0, 10)

    assert row_id > 0
    assert len(stored) == 1
    assert stored[0]["action_sequence"] == "Bash>Read"
    assert stored[0]["occurrences"] == 4
    assert stored[0]["proficiency"] == pytest.approx(0.7)
    assert stored[0]["is_habitual"] is True
    assert stored[0]["last_seen"]


def test_the_same_skill_updates_in_place(sqlite_store) -> None:
    first = sqlite_store.upsert_procedural_skill(SKILL)

    second = sqlite_store.upsert_procedural_skill({**SKILL, "occurrences": 9})

    assert first == second
    stored = sqlite_store.get_procedural_skills(0.0, 10)
    assert len(stored) == 1
    assert stored[0]["occurrences"] == 9


def test_the_proficiency_floor_filters(sqlite_store) -> None:
    sqlite_store.upsert_procedural_skill(SKILL)
    sqlite_store.upsert_procedural_skill(
        {**SKILL, "skill_id": "weak", "proficiency": 0.2}
    )

    assert len(sqlite_store.get_procedural_skills(0.0, 10)) == 2
    assert [s["skill_id"] for s in sqlite_store.get_procedural_skills(0.5, 10)] == [
        "bash-read"
    ]


def test_mined_skills_reach_the_store(sqlite_store) -> None:
    """The end-to-end path: what the session-end writer does, on SQLite."""
    from mcp_server.handlers.procedural_skill_writer import maybe_mine_skills

    sessions = [
        {"toolsUsed": ["Bash", "Read", "Edit"], "domain": "eng", "cwd": "/tmp/p"}
        for _ in range(4)
    ]

    status = maybe_mine_skills(sessions, sqlite_store)

    assert status["status"] == "ok", status
    assert status["skills_written"] > 0
    assert len(sqlite_store.get_procedural_skills(0.0, 50)) == status["skills_written"]
