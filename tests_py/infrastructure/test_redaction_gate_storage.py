"""Every storage primitive passes the redaction gate (ADR-1110).

One test per write primitive the 2026-10-21 inventory found, on SQLite (a
temporary file) and on PostgreSQL (the suite's private test database, when
reachable). After each write the whole database is searched
(``tests_py/_db_text_scan``) for the secret, in normalised form, so a copy in
a derived column (FTS augmentation, a JSON field, an array) is caught too.
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.shared import gated_files
from mcp_server.shared.log_rotation import open_rotating_log
from mcp_server.shared.process_liveness import pid_alive
from mcp_server.shared.redaction_gate import RedactingFilter, redact_text
from scripts.secret_corpus import sample, samples
from tests_py._db_text_scan import locations
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

CORPUS = samples()
ANTHROPIC = sample("anthropic-api-key").value
GH = sample("github-pat").value
PEM = sample("private-key").value
DOMAIN = "redaction-gate-test"
# source: ADR-1110 — upper bound for a detached relay to drain one line
RELAY_DEADLINE_S = 60.0


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
        yield s
        s.close()
        return
    if not _USE_PG:
        pytest.skip("PostgreSQL test database not reachable")
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    s = PgMemoryStore()
    yield s
    s.close()


def _memory(store, content: str) -> int:
    return store.insert_memory({"content": content, "tags": ["t"], "domain": DOMAIN})


def test_store_insert_redacts_content_and_every_derived_column(store):
    _memory(store, f"use {ANTHROPIC} and {GH} for ci")
    assert locations(store, ANTHROPIC) == []
    assert locations(store, GH) == []


def test_raw_update_through_the_store_connection(store):
    mid = _memory(store, "placeholder")
    sql = "UPDATE memories SET content = %s WHERE id = %s"
    if isinstance(store, SqliteMemoryStore):
        sql = sql.replace("%s", "?")
    store._conn.execute(sql, (f"leak {ANTHROPIC}", mid))
    assert locations(store, ANTHROPIC) == []


def test_cursor_execute_and_executemany(store):
    sql = (
        "INSERT INTO memory_rules (rule_type, scope, condition, action) "
        "VALUES (%s, %s, %s, %s)"
    )
    if isinstance(store, SqliteMemoryStore):
        sql = sql.replace("%s", "?")
        store._raw_conn.executemany(sql, [("soft", "global", f"if {GH}", "x")])
    else:
        with store._conn.cursor() as cur:
            cur.executemany(sql, [("soft", "global", f"if {GH}", "x")])
    with store._conn.cursor() as cur:
        cur.execute(sql, ("soft", "global", "y", f"then {ANTHROPIC}"))
    assert locations(store, GH) == []
    assert locations(store, ANTHROPIC) == []


def test_wiki_writer_on_a_caller_supplied_connection(store):
    from mcp_server.infrastructure.pg_store_wiki_pages import upsert_page

    page = {
        "rel_path": "notes/gate.md",
        "slug": "gate",
        "kind": "note",
        "title": f"title {GH}",
        "body": f"body {ANTHROPIC}",
        "domain": DOMAIN,
    }
    upsert_page(store._conn, page)
    assert locations(store, ANTHROPIC) == []
    assert locations(store, GH) == []


def test_json_and_dict_parameters_are_redacted_recursively(store):
    store.insert_checkpoint(
        {
            "session_id": "s",
            "directory_context": "/x",
            "current_task": f"task {GH}",
            "key_decisions": [{"nested": [f"deep {ANTHROPIC}"]}],
            "custom_context": f"ctx {GH}",
            "domain": DOMAIN,
        }
    )
    assert locations(store, ANTHROPIC) == []
    assert locations(store, GH) == []


def test_reads_are_not_rewritten(store):
    """Only write statements are gated: a read binds its parameter unchanged."""
    mid = _memory(store, "plain text")
    sql = "SELECT id FROM memories WHERE content = %s"
    if isinstance(store, SqliteMemoryStore):
        sql = sql.replace("%s", "?")
    assert store._conn.execute(sql, ("plain text",)).fetchone() is not None
    assert mid


@pytest.mark.skipif(not _USE_PG, reason="PostgreSQL test database not reachable")
def test_pg_pool_connection_and_copy_are_gated():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore()
    try:
        mid = _memory(store, "placeholder")
        with store.acquire_interactive() as conn:  # the anchor.py shape
            conn.execute("UPDATE memories SET content = %s WHERE id = %s", (GH, mid))
        with store.acquire_batch() as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.execute("CREATE TEMP TABLE gate_copy (v text) ON COMMIT DROP")
                with cur.copy("COPY gate_copy (v) FROM STDIN") as cp:
                    cp.write_row([f"row {ANTHROPIC}"])
                    with pytest.raises(TypeError, match="bypasses the redaction"):
                        cp.write(b"raw\n")
                copied = cur.execute("SELECT v FROM gate_copy").fetchone()
        assert ANTHROPIC not in copied["v"]
        assert locations(store, GH) == []
    finally:
        store.close()


def test_embeddings_are_computed_from_redacted_text():
    from mcp_server.infrastructure.embedding_engine import get_embedding_engine

    engine = get_embedding_engine()
    text = f"deploy with {ANTHROPIC}"
    assert engine.encode(text) == engine.encode(redact_text(text))
    assert engine.encode_batch([text]) == engine.encode_batch([redact_text(text)])


def test_gated_file_writers(tmp_path):
    gated_files.write_text(tmp_path / "a.md", f"x {GH}")
    gated_files.write_json(tmp_path / "b.json", {"k": [f"{ANTHROPIC}"]})
    gated_files.write_bytes(tmp_path / "c.md", f"z {PEM}".encode())
    gated_files.append_text(tmp_path / "d.log", f"line {GH}\n")
    for name in ("a.md", "b.json", "c.md", "d.log"):
        content = (tmp_path / name).read_text()
        assert GH not in content and ANTHROPIC not in content and PEM not in content


def test_rotating_log_stream_redacts_and_hands_out_no_descriptor(tmp_path):
    with open_rotating_log(tmp_path / "t.jsonl") as stream:
        stream.write(f'{{"err": "{ANTHROPIC}"}}\n')
        with pytest.raises(OSError, match="no raw descriptor"):
            stream.fileno()
    assert ANTHROPIC not in (tmp_path / "t.jsonl").read_text()


def test_artifact_address_is_derived_from_redacted_text(monkeypatch, tmp_path):
    from mcp_server.infrastructure import artifact_store

    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path)
    raw = f"oversized output {ANTHROPIC}\n" * 10
    path = artifact_store.store_artifact(raw)
    assert ANTHROPIC not in path.read_text()
    assert path == artifact_store.store_artifact(redact_text(raw))


def test_log_file_handler_filter_redacts_message_and_traceback(tmp_path):
    handler = logging.FileHandler(tmp_path / "h.log", encoding="utf-8")
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("redaction-gate-test")
    logger.addHandler(handler)
    try:
        logger.error("auth failed for %s", GH)
        try:
            raise ValueError(f"bad key {ANTHROPIC}")
        except ValueError:
            logger.exception("boom")
    finally:
        logger.removeHandler(handler)
        handler.close()
    text = (tmp_path / "h.log").read_text()
    assert GH not in text and ANTHROPIC not in text
    assert "[REDACTED:github-pat]" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_child_output_reaches_its_log_only_through_the_relay(tmp_path):
    from mcp_server.infrastructure.log_relay import spawn_logged

    log = tmp_path / "child.log"
    code = (
        "import sys\n"
        f"print('token {GH}', flush=True)\n"
        f"print({PEM!r}, file=sys.stderr, flush=True)\n"
    )
    spawned = spawn_logged([sys.executable, "-c", code], log, mode=0o600)
    assert spawned.child.wait(timeout=RELAY_DEADLINE_S) == 0
    assert spawned.relay.wait(timeout=RELAY_DEADLINE_S) == 0
    text = log.read_text()
    assert "[REDACTED:github-pat]" in text and "[REDACTED:private-key]" in text
    assert GH not in text and "PRIVATE KEY-----\n" not in text
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_relay_survives_the_spawner_and_drains_after_it_exits(tmp_path):
    """The hook shape: the spawner exits at once; relay and child live on."""
    log = tmp_path / "detached.log"
    repo = Path(__file__).resolve().parents[2]
    child_code = f"print({GH!r})"
    spawner = (
        "import sys\n"
        "from pathlib import Path\n"
        "from mcp_server.infrastructure.log_relay import spawn_logged\n"
        f"cmd = [sys.executable, '-c', {child_code!r}]\n"
        f"s = spawn_logged(cmd, Path({str(log)!r}))\n"
        "print(s.child.pid, s.relay.pid)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", spawner],
        capture_output=True,
        text=True,
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo)},
        check=True,
    ).stdout.split()
    deadline = time.monotonic() + RELAY_DEADLINE_S
    while time.monotonic() < deadline and any(pid_alive(int(p)) for p in out):
        time.sleep(0.05)
    assert not any(pid_alive(int(p)) for p in out)
    assert log.read_text().strip() == "[REDACTED:github-pat]"


def test_sql_script_on_a_store_connection_is_redacted(tmp_path):
    """Review of #775, N1: executescript ran literal SQL past the gate."""
    s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    try:
        s._conn.executescript(
            "INSERT INTO memory_rules (rule_type, scope, condition, action) "
            f"VALUES ('soft', 'global', 'if {GH}', 'x');"
        )
        s._conn.commit()
        assert locations(s, GH) == []
    finally:
        s.close()


def test_a_page_hash_is_taken_over_the_redacted_body(store):
    """CodeQL on #775 (py/weak-sensitive-data-hashing): the stored body_hash
    was sha256 of the body before the gate redacted it. Next to the
    redacted body, that fast hash lets anyone holding the database test
    guesses for the secret; the hash must be of what is stored."""
    import hashlib

    from mcp_server.infrastructure.pg_store_wiki_common import body_hash
    from mcp_server.infrastructure.pg_store_wiki_pages import upsert_page

    body = f"body {ANTHROPIC}"
    upsert_page(
        store._conn,
        {
            "rel_path": "notes/h.md",
            "slug": "h",
            "kind": "note",
            "title": "h",
            "body": body,
            "domain": DOMAIN,
        },
    )
    row = store._conn.execute(
        "SELECT body_hash FROM wiki.pages WHERE rel_path = %s", ("notes/h.md",)
    ).fetchone()
    raw = hashlib.sha256(body.encode()).hexdigest()
    assert body_hash(body) != raw
    assert row["body_hash"] == hashlib.sha256(redact_text(body).encode()).hexdigest()
