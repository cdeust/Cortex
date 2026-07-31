"""PG-gated tests for the T2 hook receipt channels (decision 4255039).

Falsifiable T2 criteria, per channel:

* the injected stdout carries the ⟦rcpt:id⟧ marker (correction 2);
* the persisted receipt records channel + session_id derived from the
  transcript file basename, NOT the event's divergent session_id field
  (correction 7);
* receipt items mirror exactly the injected payload, in injection order;
* superseded memories never enter the banner/briefing (correction 8).

session_start is exercised in-process (its main() spawns detached
background workers — pipeline reanalyze, consolidate — that a subprocess
test would fire on the host machine). agent_briefing and auto_recall are
exercised end-to-end as subprocesses, mirroring test_auto_recall.py.

Skipped automatically when PG is not reachable (CI without pgvector).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests_py.conftest import _USE_PG_STORE, _TEST_DB_URL  # type: ignore
import pathlib

pytestmark = pytest.mark.skipif(
    # Gated on the EFFECTIVE backend, not reachability: these fixtures seed
    # PostgreSQL directly (raw DSN / PG-only migrations) while the product
    # under test reads the resolved store. Under a sqlite-backend run they
    # seeded one store and asserted against another, so they failed for a
    # harness reason rather than a product one. SQLite coverage of these
    # paths needs backend-agnostic fixtures — tracked in #220.
    not _USE_PG_STORE,
    reason="PostgreSQL not available — hook receipts need PG schema",
)

# The event's session_id field diverges from the transcript identity
# across resume/clear chains (148/200 lines on fixture 7374abf5) — the
# receipt must record the file basename.
_TRANSCRIPT = "/tmp/claude/projects/x/sess-t2-fixture.jsonl"
_EXPECTED_SESSION = "sess-t2-fixture"
_DIVERGENT_EVENT_SESSION = "divergent-event-session-id"


def _cleanup(conn) -> None:
    conn.execute(
        "DELETE FROM injection_receipts WHERE session_id = %s",
        (_EXPECTED_SESSION,),
    )
    conn.execute("DELETE FROM memories WHERE content LIKE %s", ("HOOKRCPT_TEST%",))


@pytest.fixture()
def _db():
    """Schema (DDL + migrations, incl. the channel-enum CHECK) + clean slate."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore(database_url=_TEST_DB_URL)

    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(_TEST_DB_URL, row_factory=dict_row, autocommit=True)
    _cleanup(conn)

    yield conn

    _cleanup(conn)
    conn.close()
    try:
        store._conn.close()
    except Exception:
        pass


def _seed(
    conn,
    content: str,
    *,
    heat: float = 0.9,
    protected: bool = False,
    is_global: bool = False,
    agent: str = "",
    tags: str = "[]",
    superseded_by: int | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO memories (content, heat_base, heat_base_set_at, "
        "is_benchmark, plasticity, no_decay, is_protected, is_global, "
        "agent_context, tags, superseded_by_id) "
        "VALUES (%s, %s, NOW(), FALSE, 1.0, FALSE, %s, %s, %s, %s::jsonb, %s) "
        "RETURNING id",
        (content, heat, protected, is_global, agent, tags, superseded_by),
    ).fetchone()
    return int(row["id"])


def _receipt(conn, receipt_id: int) -> tuple[dict, list[dict]]:
    header = conn.execute(
        "SELECT session_id, channel FROM injection_receipts WHERE id = %s",
        (receipt_id,),
    ).fetchone()
    items = conn.execute(
        "SELECT memory_id, rank FROM injection_receipt_items "
        "WHERE receipt_id = %s ORDER BY rank",
        (receipt_id,),
    ).fetchall()
    return header, items


def _run_hook(module: str, event: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = _TEST_DB_URL
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    return subprocess.run(
        [sys.executable, "-m", module],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
        timeout=10,
    )


# ── session_start (in-process) ────────────────────────────────────────────


def test_session_start_banner_receipt_roundtrip(_db) -> None:
    from mcp_server.hooks import session_start as ss

    anchor_id = _seed(
        _db,
        "HOOKRCPT_TEST anchored critical fact",
        protected=True,
        tags='["_anchor"]',
    )
    hot_id = _seed(_db, "HOOKRCPT_TEST hot memory fact", heat=0.95)
    stale_id = _seed(
        _db,
        "HOOKRCPT_TEST superseded stale fact",
        heat=0.99,
        superseded_by=hot_id,
    )

    anchors = ss._fetch_anchors(_db)
    anchor_ids = {a["id"] for a in anchors}
    hot = ss._fetch_hot_memories(_db, anchor_ids)
    team = ss._fetch_team_decisions(_db, anchor_ids)

    assert anchor_id in anchor_ids
    hot_ids = [m["id"] for m in hot]
    assert hot_id in hot_ids
    # Correction 8: a corrected (superseded) fact never enters the banner,
    # regardless of heat.
    assert stale_id not in hot_ids
    assert stale_id not in anchor_ids

    event = {
        "transcript_path": _TRANSCRIPT,
        "session_id": _DIVERGENT_EVENT_SESSION,
    }
    receipt_id = ss._emit_banner_receipt(_db, event, anchors, team, hot)
    assert receipt_id is not None

    # Correction 2: the banner header carries the in-context marker.
    context = ss._build_context(anchors, hot, None, team, receipt_id=receipt_id)
    assert f"⟦rcpt:{receipt_id}⟧" in context.splitlines()[0]

    header, items = _receipt(_db, receipt_id)
    assert header["channel"] == "session_start"
    # Correction 7: transcript basename, not the divergent event field.
    assert header["session_id"] == _EXPECTED_SESSION

    expected = [m["id"] for m in (*anchors, *team, *hot)]
    assert [r["memory_id"] for r in items] == expected
    assert [r["rank"] for r in items] == list(range(len(expected)))

    # Rank order anchored to the RENDERED banner, not to the payload
    # tuple the code builds (which would be tautological): the anchored
    # fact prints before the hot fact, and their receipt ranks must
    # follow that same visible order.
    lines = context.splitlines()
    anchor_line = next(
        i for i, text in enumerate(lines) if "anchored critical fact" in text
    )
    hot_line = next(i for i, text in enumerate(lines) if "hot memory fact" in text)
    assert anchor_line < hot_line
    rank_by_id = {r["memory_id"]: r["rank"] for r in items}
    assert rank_by_id[anchor_id] < rank_by_id[hot_id]


def test_session_start_read_event_tolerates_garbage(monkeypatch) -> None:
    import io

    from mcp_server.hooks import session_start as ss

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    assert ss._read_event() == {}
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert ss._read_event() == {}


def test_session_start_empty_banner_emits_no_receipt(_db) -> None:
    from mcp_server.hooks import session_start as ss

    before = _db.execute("SELECT COUNT(*) AS c FROM injection_receipts").fetchone()["c"]
    assert ss._emit_banner_receipt(_db, {}, [], [], []) is None
    after = _db.execute("SELECT COUNT(*) AS c FROM injection_receipts").fetchone()["c"]
    assert after == before


# ── auto_recall (subprocess, end-to-end) ──────────────────────────────────


def test_auto_recall_emits_receipt_with_marker(_db) -> None:
    mid = _seed(_db, "HOOKRCPT_TEST velvetine mirandol cartography atlas")

    result = _run_hook(
        "mcp_server.hooks.auto_recall",
        {
            "prompt": "velvetine mirandol cartography atlas",
            "transcript_path": _TRANSCRIPT,
            "session_id": _DIVERGENT_EVENT_SESSION,
        },
    )

    assert result.returncode == 0
    assert "velvetine" in result.stdout.lower(), (
        f"expected injection, stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    row = _db.execute(
        "SELECT id FROM injection_receipts "
        "WHERE channel = 'auto_recall' AND session_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (_EXPECTED_SESSION,),
    ).fetchone()
    assert row is not None, "auto_recall receipt was not persisted"

    # Marker in stdout matches the persisted receipt (correction 2).
    assert f"⟦rcpt:{row['id']}⟧" in result.stdout.splitlines()[0]

    _, items = _receipt(_db, row["id"])
    assert mid in [r["memory_id"] for r in items]


# ── agent_briefing (subprocess, end-to-end) ───────────────────────────────


def test_agent_briefing_emits_receipt_with_marker(_db) -> None:
    mid = _seed(
        _db,
        "HOOKRCPT_TEST zephyrine quantalum brokerage reconciliation ledger",
        agent="engineer",
    )
    # Pass 2 (TMS directory layer): a protected global decision from
    # ANOTHER agent enters the briefing regardless of keywords — it must
    # be attested by the same receipt, ranked after the agent-scoped pass.
    team_id = _seed(
        _db,
        "HOOKRCPT_TEST team decision on rollout gates",
        protected=True,
        is_global=True,
        agent="architect",
    )

    result = _run_hook(
        "mcp_server.hooks.agent_briefing",
        {
            "agent_name": "engineer",
            "agent_type": "custom",
            "prompt": (
                "zephyrine quantalum brokerage reconciliation ledger "
                "please review carefully"
            ),
            "cwd": "/tmp",
            "transcript_path": _TRANSCRIPT,
            "session_id": _DIVERGENT_EVENT_SESSION,
        },
    )

    assert result.returncode == 0
    assert "zephyrine" in result.stdout.lower(), (
        f"expected briefing, stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    row = _db.execute(
        "SELECT id FROM injection_receipts "
        "WHERE channel = 'agent_briefing' AND session_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (_EXPECTED_SESSION,),
    ).fetchone()
    assert row is not None, "agent_briefing receipt was not persisted"

    assert f"⟦rcpt:{row['id']}⟧" in result.stdout.splitlines()[0]

    _, items = _receipt(_db, row["id"])
    injected = [r["memory_id"] for r in items]
    assert mid in injected
    # Pass 2 attested by the same receipt, after the agent-scoped memory.
    assert team_id in injected
    assert injected.index(mid) < injected.index(team_id)
    assert "team:architect" in result.stdout


# ── channel enum on live PG (decision 4255039 correction 3) ──────────────


def test_pg_rejects_unknown_channel_live(_db) -> None:
    # The DDL CHECK is behavior, not text: an out-of-band writer with an
    # out-of-enum channel must be rejected by the database itself.
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        _db.execute(
            "INSERT INTO injection_receipts (session_id, channel) "
            "VALUES (%s, 'banner')",
            (_EXPECTED_SESSION,),
        )


def test_channel_enum_migration_restores_dropped_constraint(_db) -> None:
    # Exercise the real T1→T2 path: on a T1 database the table exists with
    # free-TEXT channel AND schema_meta records the T1 DDL hash — which
    # differs from the T2 hash, so _init_schema replays the DDL and the
    # MIGRATIONS_DDL DO block adds the CHECK. Simulate that state by
    # dropping the constraint and invalidating the recorded revision
    # (schema init is hash-gated; without this it correctly no-ops).
    _db.execute(
        "ALTER TABLE injection_receipts "
        "DROP CONSTRAINT IF EXISTS injection_receipts_channel_enum"
    )
    _db.execute("DELETE FROM schema_meta WHERE id = 1")
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore(database_url=_TEST_DB_URL)
    try:
        row = _db.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'injection_receipts_channel_enum'"
        ).fetchone()
        assert row is not None, "migration did not restore the channel CHECK"
    finally:
        try:
            store._conn.close()
        except Exception:
            pass


def test_agent_briefing_skips_superseded_prior_work(_db) -> None:
    # Correction 8 on the briefing path: the agent-scoped pass must not
    # brief with a corrected fact.
    current = _seed(
        _db,
        "HOOKRCPT_TEST ombrelline daguerre synthesis current",
        agent="engineer",
    )
    stale = _seed(
        _db,
        "HOOKRCPT_TEST ombrelline daguerre synthesis stale",
        agent="engineer",
        superseded_by=current,
    )

    result = _run_hook(
        "mcp_server.hooks.agent_briefing",
        {
            "agent_name": "engineer",
            "agent_type": "custom",
            # "work"/"please"/"ensure" are briefing stopwords — the FTS
            # AND-query reduces to the three words both memories share.
            "prompt": "ombrelline daguerre synthesis work please ensure",
            "cwd": "/tmp",
            "transcript_path": _TRANSCRIPT,
            "session_id": _DIVERGENT_EVENT_SESSION,
        },
    )

    assert result.returncode == 0
    row = _db.execute(
        "SELECT id FROM injection_receipts "
        "WHERE channel = 'agent_briefing' AND session_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (_EXPECTED_SESSION,),
    ).fetchone()
    assert row is not None
    _, items = _receipt(_db, row["id"])
    injected = [r["memory_id"] for r in items]
    assert current in injected
    assert stale not in injected
