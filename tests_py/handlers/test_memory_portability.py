"""Per-project export and import of memories (audit A8, GDPR art. 20; ADR-1113).

The audit found no export of a project's memories (``grep -rliE 'def .*export'
mcp_server/handlers`` empty). Each test runs on SQLite (temporary file) and on
PostgreSQL (the suite's private database, when reachable).
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from mcp_server.handlers import memory_portability as portability
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from scripts.secret_corpus import sample
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

RUN = uuid.uuid4().hex[:10]
PROJECT = f"/work/{RUN}/app"
GITHUB = sample("github-pat").value


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    else:
        if not _USE_PG:
            pytest.skip("PostgreSQL test database not reachable")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        s = PgMemoryStore()
    yield s
    s.close()


def _seed(store) -> None:
    rows = [
        (f"decision {RUN}: use SQLite by default", PROJECT, False),
        (f"note {RUN} in a sub-directory", f"{PROJECT}/src/api", False),
        (f"sibling {RUN} must not leak", f"/work/{RUN}/app-other", False),
        (f"parent {RUN} is another project", f"/work/{RUN}", False),
        (f"global {RUN} convention", "", True),
    ]
    for content, directory, is_global in rows:
        store.insert_memory(
            {
                "content": content,
                "tags": ["t"],
                "domain": "d",
                "directory_context": directory,
                "is_global": is_global,
            }
        )


def _contents(path: Path) -> list[str]:
    _header, records = portability.read_export(path)
    return sorted(r["content"] for r in records)


def test_export_holds_the_project_and_its_subdirectories_only(store, tmp_path):
    _seed(store)
    out = tmp_path / "export.jsonl"
    header = portability.export_project(store, PROJECT, out)
    assert header["count"] == 2
    assert _contents(out) == sorted(
        [f"decision {RUN}: use SQLite by default", f"note {RUN} in a sub-directory"]
    )


def test_global_memories_are_included_only_when_asked(store, tmp_path):
    _seed(store)
    out = tmp_path / "export.jsonl"
    portability.export_project(store, PROJECT, out, include_global=True)
    assert f"global {RUN} convention" in _contents(out)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_the_export_file_is_owner_only_and_self_describing(store, tmp_path):
    _seed(store)
    out = tmp_path / "export.jsonl"
    portability.export_project(store, PROJECT, out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    header = json.loads(out.read_text().splitlines()[0])
    assert header["format"] == "cortex-memory-export" and header["version"] == 1
    assert header["fields"] == list(portability.EXPORT_FIELDS)


def test_a_secret_stored_before_the_gate_leaves_the_store_redacted(store, tmp_path):
    """Rows written before ADR-1110 can hold a secret; the export never does."""
    mid = store.insert_memory(
        {
            "content": "placeholder",
            "tags": [],
            "domain": "d",
            "directory_context": PROJECT,
        }
    )
    raw_update = "UPDATE memories SET content = %s WHERE id = %s"
    # an ungated connection stands in for a row written before the gate
    if isinstance(store, SqliteMemoryStore):
        with sqlite3.connect(store._connection_registry._target) as raw:
            raw.execute(raw_update.replace("%s", "?"), (f"token {GITHUB}", mid))
    else:
        import psycopg

        with psycopg.connect(store._url, autocommit=True) as raw:
            raw.execute(raw_update, (f"token {GITHUB}", mid))
    out = tmp_path / "export.jsonl"
    portability.export_project(store, PROJECT, out)
    assert GITHUB not in out.read_text()
    assert "[REDACTED:github-pat]" in out.read_text()


def test_round_trip_into_another_project_and_twice_adds_nothing(store, tmp_path):
    _seed(store)
    out = tmp_path / "export.jsonl"
    portability.export_project(store, PROJECT, out)
    target = f"/elsewhere/{RUN}/app"
    first = portability.import_export(store, out, into_project_root=target)
    again = portability.import_export(store, out, into_project_root=target)
    assert first == {"imported": 2, "skipped": 0}
    assert again == {"imported": 0, "skipped": 2}
    moved = tmp_path / "moved.jsonl"
    portability.export_project(store, target, moved)
    assert _contents(moved) == _contents(out)
    _header, records = portability.read_export(moved)
    assert {r["directory_context"] for r in records} == {target, f"{target}/src/api"}


def test_a_file_that_is_not_an_export_is_refused(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"format": "something-else"}\n')
    with pytest.raises(ValueError, match="not a cortex-memory-export"):
        portability.read_export(bad)
    truncated = tmp_path / "truncated.jsonl"
    header = {
        "format": "cortex-memory-export",
        "version": 1,
        "count": 3,
        "fields": list(portability.EXPORT_FIELDS),
        "project_root": "/p",
    }
    truncated.write_text(json.dumps(header) + "\n")
    with pytest.raises(ValueError, match="header says 3"):
        portability.read_export(truncated)


def _cli(db: Path, *args: str) -> subprocess.CompletedProcess:
    """Run ``python -m mcp_server.portability`` against the SQLite file ``db``."""
    env = {
        **os.environ,
        "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
        "CORTEX_MEMORY_DB_PATH": str(db),
        "CORTEX_MEMORY_SQLITE_FALLBACK_PATH": str(db),
        # offline: the embedding model is already cached or falls back
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.portability", *args],
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=300,  # source: ADR-1113 — bound for a cold model load
    )


def test_the_command_line_exports_and_imports(tmp_path):
    """End to end through ``python -m mcp_server.portability`` on SQLite."""
    db = tmp_path / "cli.db"
    store = SqliteMemoryStore(str(db))
    _seed(store)
    store.close()
    out = tmp_path / "cli.jsonl"
    exported = _cli(db, "export", PROJECT, str(out))
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["count"] == 2
    imported = _cli(db, "import", str(out), "--into", f"/copy/{RUN}")
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout) == {"imported": 2, "skipped": 0}
    refused = _cli(db, "import", str(tmp_path / "missing.jsonl"))
    assert refused.returncode == 1
    assert "cortex portability:" in refused.stderr


def _crafted(tmp_path: Path, root: str, records: list[dict]) -> Path:
    """An export file written by hand, as an attacker would (review of #775, B2)."""
    header = {
        "format": "cortex-memory-export",
        "version": 1,
        "exported_at": "2026-10-21T00:00:00+00:00",
        "project_root": root,
        "include_global": False,
        "count": len(records),
        "fields": list(portability.EXPORT_FIELDS),
    }
    base = {field: None for field in portability.EXPORT_FIELDS}
    rows = [{**base, "tags": [], **r} for r in records]
    path = tmp_path / "crafted.jsonl"
    lines = [json.dumps(header)] + [json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def _stored(store, content: str) -> list[dict]:
    rows = store._conn.execute(
        "SELECT directory_context, is_global, is_protected, is_team_decision "
        "FROM memories WHERE content = %s",
        (content,),
    ).fetchall()
    return [dict(r) for r in rows]


@pytest.mark.parametrize(
    "directory",
    [
        f"/work/{RUN}/b/planted",  # another project
        f"/work/{RUN}/a/../b",  # escapes after normalisation
        f"/work/{RUN}/a/src/../../b",
        "relative/path",
        "",
    ],
)
def test_import_refuses_a_record_outside_the_file_root(store, tmp_path, directory):
    content = f"planted {RUN} {uuid.uuid4().hex[:6]}"
    path = _crafted(
        tmp_path,
        f"/work/{RUN}/a",
        [
            {"content": f"ok {content}", "directory_context": f"/work/{RUN}/a"},
            {"content": content, "directory_context": directory},
        ],
    )
    with pytest.raises(ValueError, match="outside"):
        portability.import_export(store, path, into_project_root=f"/work/{RUN}/c")
    assert _stored(store, content) == [] and _stored(store, f"ok {content}") == []


def test_import_turns_flags_off_unless_trusted(store, tmp_path):
    root = f"/work/{RUN}/flags"
    flags = {"is_global": True, "is_protected": True, "is_team_decision": True}
    records = [{"content": f"flagged {RUN}", "directory_context": root, **flags}]
    portability.import_export(store, _crafted(tmp_path, root, records))
    (row,) = _stored(store, f"flagged {RUN}")
    assert not any(row[k] for k in flags), row
    trusted = [{"content": f"trusted {RUN}", "directory_context": root, **flags}]
    path = _crafted(tmp_path, root, trusted)
    portability.import_export(store, path, trust_flags=True)
    (row,) = _stored(store, f"trusted {RUN}")
    assert all(row[k] for k in flags), row


@pytest.mark.parametrize(
    "bad",
    [
        {"content": 42},
        {"content": ""},
        {"tags": "not-a-list"},
        {"tags": [1, 2]},
        {"importance": "high"},
        {"importance": float("nan")},
        {"is_protected": "yes"},
        {"domain": ["d"]},
        {"created_at": "yesterday"},
    ],
    ids=lambda b: next(iter(b)) + "=" + repr(next(iter(b.values())))[:12],
)
def test_import_type_checks_every_field(store, tmp_path, bad):
    root = f"/work/{RUN}/types"
    record = {"content": f"typed {RUN}", "directory_context": root, **bad}
    with pytest.raises(ValueError):
        portability.import_export(store, _crafted(tmp_path, root, [record]))


def test_export_prefix_is_case_sensitive(store, tmp_path):
    """Review of #775, N7: SQLite LIKE ignores ASCII case, so a sibling that
    differs by case only was exported."""
    for directory in (PROJECT, PROJECT.replace("/app", "/APP") + "/x"):
        store.insert_memory(
            {
                "content": f"case {RUN} {directory}",
                "tags": [],
                "domain": "d",
                "directory_context": directory,
            }
        )
    out = tmp_path / "export.jsonl"
    portability.export_project(store, PROJECT, out)
    assert _contents(out) == [f"case {RUN} {PROJECT}"]
