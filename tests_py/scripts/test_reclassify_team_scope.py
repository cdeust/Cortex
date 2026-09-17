"""Operator repair invariants. source: ADR-1083"""

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.reclassify_team_scope import (
    ScopeMappings,
    ScopeRow,
    classify,
    load_mappings,
    make_report,
    run,
)
from scripts.reclassify_team_scope_db import ScopeDatabase, verify_backup


@pytest.fixture
def row():
    return ScopeRow(
        1,
        "DECISION: use project-specific parser",
        [],
        "project-a",
        "/project-a",
        "agent-a",
        True,
        False,
    )


@pytest.fixture
def mappings():
    return ScopeMappings({}, {}, frozenset())


def test_project_decision_is_team_only(row, mappings):
    change = classify(row, mappings)
    assert (change.directory_context, change.is_global, change.is_team_decision) == (
        "/project-a",
        False,
        True,
    )


def test_global_detector_and_explicit_override(row, mappings):
    universal = replace(
        row,
        content="Clean architecture and dependency injection: SOLID composition root",
    )
    assert classify(universal, mappings).is_global
    assert classify(row, replace(mappings, keep_global_ids=frozenset({1}))).is_global


def test_unknown_project_remains_unchanged(row, mappings):
    unknown = replace(row, domain="", directory_context="")
    change = classify(unknown, mappings)
    assert change.is_global and not change.is_team_decision
    assert make_report([unknown], mappings)["unresolved_ids"] == [1]
    assert make_report([unknown], mappings)["change_count"] == 0


def test_domain_mapping_and_owner_mapping(row, mappings):
    unknown = replace(row, directory_context="")
    domain = replace(mappings, domains={"project-a": "/verified-a"})
    assert classify(unknown, domain).directory_context == "/verified-a"
    owner = replace(domain, memories={"1": "/owner-a"})
    assert classify(unknown, owner).directory_context == "/owner-a"
    assert classify(row, owner).directory_context == "/project-a"


def test_nondecision_and_existing_marker(row, mappings):
    ordinary = replace(row, content="The parser uses XML.")
    assert not classify(ordinary, mappings).is_team_decision
    assert classify(replace(ordinary, is_team_decision=True), mappings).is_team_decision
    assert not classify(replace(row, agent_context=""), mappings).is_team_decision


def test_a_global_row_the_defect_could_not_have_produced_stays_global(row, mappings):
    """ADR-0200 promoted decisions written under an agent context. A global
    row with no agent context, or with non-decision content, was made global
    by an explicit act: clearing it would lose the owner's intent (#611)."""
    explicit = replace(
        row, content="The parser uses XML.", agent_context="", is_global=True
    )
    kept = classify(explicit, mappings)
    assert kept.is_global
    assert kept.reason == "global_origin_not_the_defect"
    no_agent = classify(replace(row, agent_context="", is_global=True), mappings)
    assert no_agent.is_global
    promoted = classify(replace(row, is_global=True), mappings)
    assert not promoted.is_global
    assert promoted.is_team_decision


def test_the_owner_can_clear_a_global_the_script_would_keep(row):
    explicit = replace(row, content="The parser uses XML.", is_global=True)
    owner = ScopeMappings({}, {}, frozenset(), frozenset({1}))
    assert not classify(explicit, owner).is_global


def test_an_id_cannot_be_both_kept_and_cleared(tmp_path):
    file = tmp_path / "mappings.json"
    file.write_text(json.dumps({"keep_global_ids": [7], "clear_global_ids": [7]}))
    with pytest.raises(ValueError, match="both kept and cleared"):
        load_mappings(file)


def test_mapping_validation(tmp_path):
    file = tmp_path / "mappings.json"
    file.write_text(
        json.dumps(
            {
                "domains": {"a": str(tmp_path)},
                "memories": {"1": str(tmp_path)},
                "keep_global_ids": [2],
            }
        )
    )
    result = load_mappings(file)
    assert result.domains == {"a": str(tmp_path)}
    assert result.keep_global_ids == frozenset({2})
    assert load_mappings(None) == ScopeMappings({}, {}, frozenset())


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"typo": {}},
        {"domains": []},
        {"domains": {"": "/a"}},
        {"domains": {"a": 4}},
        {"domains": {"a": "relative"}},
        {"memories": {"bad": "/tmp"}},
        {"keep_global_ids": [True]},
        {"keep_global_ids": "1"},
    ],
)
def test_bad_mappings_fail(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_mappings(path)


def seed(path: Path, marker: bool = True):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, tags TEXT, "
            "domain TEXT, directory_context TEXT, agent_context TEXT, "
            "is_global INTEGER, is_benchmark INTEGER, superseded_by_id INTEGER"
            + (", is_team_decision INTEGER DEFAULT 0" if marker else "")
            + ")"
        )
        db.execute(
            "CREATE VIEW current_memories AS SELECT * FROM memories "
            "WHERE superseded_by_id IS NULL"
        )
        db.executemany(
            "INSERT INTO memories (id,content,tags,domain,directory_context,"
            "agent_context,is_global,is_benchmark,superseded_by_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    1,
                    "DECISION: use project-specific parser",
                    "[]",
                    "a",
                    "/a",
                    "agent",
                    1,
                    0,
                    None,
                ),
                (2, "DECISION: unknown project", None, None, None, "agent", 1, 0, None),
                (3, "DECISION: history", "[]", "a", "/a", "agent", 1, 0, 1),
                (4, "DECISION: benchmark", "[]", "a", "/a", "agent", 1, 1, None),
            ],
        )


def arguments(path, apply=False):
    return SimpleNamespace(
        mappings=None, apply=apply, database_url=None, sqlite_path=path, backup=None
    )


def test_dry_run_apply_and_second_run_are_idempotent(tmp_path):
    path = tmp_path / "scope.db"
    seed(path)
    before = path.read_bytes()
    report = run(arguments(path))
    assert report["candidate_count"] == 2
    assert report["change_count"] == report["clear_global_count"] == 1
    assert not report["applied"]
    assert path.read_bytes() == before
    assert run(arguments(path, True))["change_count"] == 1
    assert run(arguments(path, True))["change_count"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT id,is_global,is_team_decision FROM memories ORDER BY id"
        ).fetchall() == [(1, 0, 1), (2, 1, 0), (3, 1, 0), (4, 1, 0)]
        assert db.execute(
            "SELECT superseded_by_id FROM memories WHERE id=3"
        ).fetchone() == (1,)


def test_old_schema_supports_dry_run_but_refuses_apply(tmp_path):
    path = tmp_path / "old.db"
    seed(path, marker=False)
    assert run(arguments(path))["change_count"] == 1
    with pytest.raises(ValueError, match="schema migration"):
        run(arguments(path, True))


def test_partial_failure_rolls_back(tmp_path):
    path = tmp_path / "scope.db"
    seed(path)
    with pytest.raises(RuntimeError, match="exactly row"):
        with ScopeDatabase(None, path) as db:
            db.apply_changes(
                [
                    {
                        "id": 1,
                        "directory_context": "/a",
                        "is_global": False,
                        "is_team_decision": True,
                    },
                    {
                        "id": 99,
                        "directory_context": "/a",
                        "is_global": False,
                        "is_team_decision": True,
                    },
                ]
            )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT is_global FROM memories WHERE id=1").fetchone() == (
            1,
        )


def test_missing_database_and_backup_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="existing database"):
        ScopeDatabase(None, tmp_path / "missing")
    with pytest.raises(ValueError, match="existing --backup"):
        verify_backup(None)
    backup = tmp_path / "invalid.dump"
    backup.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="custom-format"):
        verify_backup(backup)


def test_backup_requires_table_data_and_full_decode(tmp_path, monkeypatch):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"PGDMP")
    calls = []

    def restored(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="123; 0 456 TABLE DATA public memories owner")

    monkeypatch.setattr("scripts.reclassify_team_scope_db.subprocess.run", restored)
    verify_backup(archive)
    assert [call[0][1] for call in calls] == ["--list", "--file"]
    assert all(call[1]["check"] for call in calls)
    monkeypatch.setattr(
        "scripts.reclassify_team_scope_db.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="SCHEMA public"),
    )
    with pytest.raises(ValueError, match="table data"):
        verify_backup(archive)


def test_noncanonical_mapping_rejected(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"domains": {"a": str(child / "..")}}))
    with pytest.raises(ValueError, match="canonical"):
        load_mappings(mapping)
