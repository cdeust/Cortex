"""The wiki pipeline on the SQLite backend (issue #206).

Regression tests for a pipeline that was silently dead on SQLite — the
default backend for plugin installs, `.mcpb`/Cowork, and every sandboxed
launch (PRIVACY.md lines 26-38). `PsycopgCompatConnection` had no
`cursor()`, so all seven handlers raised AttributeError, each error was
recorded as a string, and the caller returned a success-shaped payload with
zero pages and no log line.

Every test here fails on the pre-fix code. The ones that assert COUNTS
rather than merely "no exception" are the load-bearing ones: two of the
eight defects (untranslated `%(name)s` placeholders, and the PostgreSQL
empty-array literal `'{}'` in wiki_resolve) produced stages that reported
success while doing nothing at all. A test that only asserted "no error
raised" would have passed against both.

Backend selection: env-var driven through the real composition root
(`get_memory_settings` -> `get_shared_store`), not a hand-built store, so
the handlers' own `_get_store()` is what is under test.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from mcp_server.infrastructure.sqlite_compat import (
    PsycopgCompatConnection,
    _translate_sql,
)


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    """Point the whole composition root at a fresh SQLite database."""
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


@pytest.fixture()
def seeded_store(sqlite_store):
    """A store holding memories and entities the pipeline can act on."""
    for name in ("pgvector", "HNSW", "FlashRank", "SQLite", "WRRF"):
        sqlite_store.insert_entity({"name": name, "type": "concept", "domain": "eng"})
    for text in (
        "We decided to use pgvector because HNSW gives sublinear ANN search.",
        "FlashRank silently failed to download, invalidating six benchmarks.",
        "Observation: SQLite is the default backend for plugin installs.",
        "We chose WRRF fusion over plain RRF because heat needed weights.",
    ):
        sqlite_store.insert_memory(
            {"content": text, "domain": "eng", "memory_type": "decision"}
        )
    return sqlite_store


# ── The root cause ───────────────────────────────────────────────────────


def _compat_conn():
    """A compat connection configured the way SqliteMemoryStore configures it."""
    import sqlite3

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    return PsycopgCompatConnection(raw)


def test_compat_connection_exposes_cursor():
    """AttributeError here was the whole of issue #206."""
    with _compat_conn().cursor() as cur:
        cur.execute("SELECT 1 AS n")
        assert cur.fetchone() == {"n": 1}


def test_cursor_accepts_row_factory_kwarg():
    """29 shared call sites pass psycopg's row_factory=dict_row."""
    with _compat_conn().cursor(row_factory=dict) as cur:
        cur.execute("SELECT 1 AS n")
        assert cur.fetchall() == [{"n": 1}]


def test_wiki_tables_exist_on_sqlite(sqlite_store):
    rows = sqlite_store._raw_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wiki_%'"
    ).fetchall()
    assert {r[0] for r in rows} == {
        "wiki_claim_events",
        "wiki_concepts",
        "wiki_drafts",
        "wiki_pages",
        "wiki_links",
        "wiki_citations",
        "wiki_page_sources",
        "wiki_memos",
    }


# ── The JSON codec: arrays must not come back as strings ─────────────────


def test_entity_ids_round_trip_as_list_not_string(sqlite_store):
    """A JSON string here would iterate character-wise, not by id.

    wiki_emerge.py does `for eid in c.get("entity_ids") or []`. If this
    column returned "[7, 8]" the loop would silently yield '[', '7', ...
    — garbage entity ids and no exception. This is the assertion that
    pins the contract.
    """
    conn = sqlite_store._conn
    conn.execute(
        "INSERT INTO wiki.claim_events (text, entity_ids) VALUES (%s, %s)",
        ("a claim", [7, 8, 9]),
    )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT entity_ids FROM wiki.claim_events")
        value = cur.fetchone()["entity_ids"]

    assert value == [7, 8, 9]
    assert isinstance(value, list)
    assert [eid for eid in value] == [7, 8, 9]


def test_array_length_predicate_matches_populated_arrays(sqlite_store):
    conn = sqlite_store._conn
    conn.execute(
        "INSERT INTO wiki.claim_events (text, entity_ids) VALUES (%s, %s)",
        ("populated", [1, 2]),
    )
    conn.execute(
        "INSERT INTO wiki.claim_events (text, entity_ids) VALUES (%s, %s)",
        ("empty", []),
    )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT text FROM wiki.claim_events WHERE array_length(entity_ids, 1) > 0"
        )
        assert [r["text"] for r in cur.fetchall()] == ["populated"]


# ── SQL translation: one case per PostgreSQL-ism the port had to handle ──


_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


@pytest.mark.parametrize(
    "sql,expected",
    [
        # Schema flattening — SQLite has no namespaces.
        ("SELECT 1 FROM wiki.pages", "SELECT 1 FROM wiki_pages"),
        # Placeholders: named (pyformat) and positional.
        ("SELECT %(name)s", "SELECT :name"),
        ("SELECT %s", "SELECT ?"),
        # Arrays are JSON under SQLite.
        (
            "SELECT array_length(entity_ids, 1)",
            "SELECT json_array_length(entity_ids)",
        ),
        ("SELECT %s::int[]", "SELECT ?"),
        ("SELECT %s::jsonb", "SELECT ?"),
        (
            "WHERE id = ANY(%s)",
            "WHERE id IN (SELECT value FROM json_each(?))",
        ),
        (
            "WHERE entity_ids && %s",
            "WHERE EXISTS (SELECT 1 FROM json_each(entity_ids) AS _ovl_l "
            "JOIN json_each(?) AS _ovl_r ON _ovl_l.value = _ovl_r.value)",
        ),
        # Statement-shape differences.
        ("UPDATE wiki.links l SET x = 1", "UPDATE wiki_links AS l SET x = 1"),
        ("SELECT a IS DISTINCT FROM b", "SELECT a IS NOT b"),
        # DDL spellings.
        (
            "CREATE TABLE t (id SERIAL PRIMARY KEY)",
            "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        ),
        ("CREATE TABLE t (ts TIMESTAMPTZ)", "CREATE TABLE t (ts TEXT)"),
        ("INSERT INTO t (ts) VALUES (NOW())", f"INSERT INTO t (ts) VALUES ({_NOW})"),
        # DEFAULT NOW() has its own rule (it must keep the DEFAULT keyword
        # and wrap the expression in parentheses), and the strftime format
        # is case-sensitive: %Y is a 4-digit year, %y a 2-digit one.
        (
            "CREATE TABLE t (ts TIMESTAMPTZ DEFAULT NOW())",
            f"CREATE TABLE t (ts TEXT DEFAULT ({_NOW}))",
        ),
        # Uppercase schema qualification must flatten too.
        ("SELECT 1 FROM WIKI.PAGES", "SELECT 1 FROM wiki_PAGES"),
    ],
)
def test_translate_sql_handles_postgres_constructs(sql, expected):
    """Exact-output assertions.

    Deliberately not `fragment in output`: a scoped mutation run over
    `_translate_sql` left 47 mutants alive against fragment matching, because
    a mutant may corrupt the REST of the statement while the fragment still
    appears. Comparing the whole string is what pins each rewrite.
    """
    assert _translate_sql(sql) == expected


def test_translate_sql_drops_xmax_but_keeps_returning_id():
    """`RETURNING id, (xmax = 0) AS inserted` left a `,` syntax error."""
    assert _translate_sql(
        "INSERT INTO wiki.pages (slug) VALUES (%s) RETURNING id, (xmax = 0) AS inserted"
    ) == ("INSERT INTO wiki_pages (slug) VALUES (?) RETURNING id")


def test_translate_sql_is_idempotent_on_already_translated_sql():
    """Negative control: translating twice must not corrupt the output."""
    once = _translate_sql("SELECT id FROM wiki.pages WHERE id = ANY(%s)")
    assert _translate_sql(once) == once


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("select 1 from wiki.pages", "select 1 from wiki_pages"),
        ("where id = any(%s)", "where id IN (SELECT value FROM json_each(?))"),
        ("select a is distinct from b", "select a IS NOT b"),
        (
            "create table t (id serial primary key)",
            "create table t (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        ),
        ("create table t (ts timestamptz)", "create table t (ts TEXT)"),
        ("insert into t (ts) values (now())", f"insert into t (ts) values ({_NOW})"),
        (
            "select array_length(entity_ids, 1)",
            "select json_array_length(entity_ids)",
        ),
        # The alias rule rewrites the keywords themselves, so they come back
        # uppercase regardless of how they were written.
        ("update wiki.links l set x = 1", "UPDATE wiki_links AS l SET x = 1"),
    ],
)
def test_translate_sql_is_case_insensitive(sql, expected):
    """Every rewrite carries re.IGNORECASE; lowercase SQL must translate too.

    Without these cases a mutant that drops `flags=re.IGNORECASE` from any
    rule survives, since the uppercase-only fixtures still match.
    """
    assert _translate_sql(sql) == expected


def test_returning_is_stripped_when_the_runtime_lacks_native_support(monkeypatch):
    """Exercises the pre-3.35 branch, which this runtime never takes.

    Without this the whole `if not _SUPPORTS_RETURNING:` arm is unreachable
    here (SQLite 3.35 added RETURNING in 2021), so every mutant of it
    survived a scoped mutation run — the branch was shipping untested.

    `_SUPPORTS_RETURNING` is patched on `sqlite_sql_translate` — the module
    that DEFINES `_translate_sql`/`_returning_was_stripped` (issue #260
    split) — not on `sqlite_compat`, which only re-exports the names via
    import. Patching the re-exported copy would be a silent no-op: the
    functions read the flag from their own module's globals.
    """
    import mcp_server.infrastructure.sqlite_compat as sc
    import mcp_server.infrastructure.sqlite_sql_translate as sqltr

    monkeypatch.setattr(sqltr, "_SUPPORTS_RETURNING", False)

    assert sc._translate_sql(
        "INSERT INTO wiki.pages (slug) VALUES (%s) RETURNING id"
    ) == ("INSERT INTO wiki_pages (slug) VALUES (?) ")
    assert sc._returning_was_stripped("INSERT INTO t (a) VALUES (1) RETURNING id")
    assert not sc._returning_was_stripped("SELECT 1")


def test_stripped_returning_synthesises_the_insert_id(monkeypatch):
    """With RETURNING stripped, fetchone() must still yield the new id.

    pg_store_wiki_common._returning_id RAISES on None, so every bulk wiki
    insert depends on this synthesis when running below SQLite 3.35.

    See `test_returning_is_stripped_when_the_runtime_lacks_native_support`
    for why the patch target is `sqlite_sql_translate`, not `sqlite_compat`.
    """
    import mcp_server.infrastructure.sqlite_sql_translate as sqltr

    monkeypatch.setattr(sqltr, "_SUPPORTS_RETURNING", False)

    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO t (a) VALUES (%s) RETURNING id", ("x",))
        assert cur.fetchone() == {"id": 1}


def test_translate_sql_leaves_unaliased_update_alone():
    """Negative control: the alias rule must not rewrite a plain UPDATE."""
    assert _translate_sql("UPDATE wiki.pages SET heat = %s") == (
        "UPDATE wiki_pages SET heat = ?"
    )


# ── RETURNING handling and cursor state ──────────────────────────────────


def test_returning_was_stripped_tracks_native_support():
    """The flag must mean "stripped", not merely "RETURNING was present".

    If it meant the latter, a filtered-out upsert (body_hash unchanged, so
    DO UPDATE ... WHERE matches nothing) would have its `None` replaced by a
    synthesised `{"id": lastrowid}` — reporting a write that never happened,
    with an id that is not even the right row.
    """
    from mcp_server.infrastructure.sqlite_sql_translate import (
        _SUPPORTS_RETURNING,
        _returning_was_stripped,
    )

    assert _returning_was_stripped("SELECT 1") is False
    assert _returning_was_stripped("INSERT INTO t (a) VALUES (1) RETURNING id") is (
        not _SUPPORTS_RETURNING
    )


def test_cursor_reports_rowcount_and_lastrowid():
    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO t (a) VALUES (%s)", ("x",))
        assert cur.lastrowid == 1
        assert cur.rowcount == 1


def test_cursor_fetchone_returns_none_when_no_rows_and_no_returning():
    """Without a stripped RETURNING there is nothing to synthesise."""
    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM t")
        assert cur.fetchone() is None


def test_cursor_closes_on_context_exit():
    conn = _compat_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS n")
    with pytest.raises(sqlite3.ProgrammingError):
        cur.execute("SELECT 1")


def test_cursor_context_does_not_swallow_exceptions():
    """`__exit__` must return False.

    Returning True would SUPPRESS any exception raised inside
    `with conn.cursor() as cur:` — turning a failed wiki stage into a
    silent no-op, which is the exact failure mode issue #206 is about.
    """
    conn = _compat_conn()
    with pytest.raises(ValueError, match="boom"):
        with conn.cursor():
            raise ValueError("boom")


def test_fresh_cursor_has_psycopg_shaped_defaults():
    """Pre-execute state: no row written, rowcount unknown (-1)."""
    with _compat_conn().cursor() as cur:
        assert cur.lastrowid is None
        assert cur.rowcount == -1
        assert cur._had_returning is False


def test_returning_detection_is_case_insensitive():
    from mcp_server.infrastructure.sqlite_sql_translate import (
        _SUPPORTS_RETURNING,
        _returning_was_stripped,
    )

    assert _returning_was_stripped("insert into t (a) values (1) returning id") is (
        not _SUPPORTS_RETURNING
    )


def test_connection_execute_returns_rows_as_dicts():
    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    conn.execute("INSERT INTO t (a) VALUES (%s)", ("x",))
    assert conn.execute("SELECT a FROM t").fetchall() == [{"a": "x"}]
    assert conn.execute("SELECT a FROM t").fetchone() == {"a": "x"}


# ── _CompatCursor / PsycopgCompatConnection field wiring (issue #260 ─────
# boy-scout: surfaced by a scoped mutation run against sqlite_compat.py
# while fixing the datetime-adapter bug — these pins were missing entirely,
# not merely weak, so mutants of `_CompatCursor.__init__`/`fetchone` and
# `PsycopgCompatConnection.execute` survived).


def test_compat_cursor_had_returning_defaults_to_false():
    """`_CompatCursor` is instantiated directly here, not through
    `PsycopgCompatConnection.execute` (which always passes every keyword
    explicitly) — pinning the class's own declared default independent of
    its one current caller."""
    import sqlite3

    from mcp_server.infrastructure.sqlite_compat import _CompatCursor

    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    cur = raw.execute("SELECT id FROM t")  # no rows
    wrapped = _CompatCursor(cur, lastrowid=5)  # had_returning NOT passed
    assert wrapped.fetchone() is None


def test_compat_cursor_rowcount_mirrors_the_wrapped_cursor():
    import sqlite3

    from mcp_server.infrastructure.sqlite_compat import _CompatCursor

    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    raw.execute("INSERT INTO t (id) VALUES (1)")
    cur = raw.execute("UPDATE t SET id = 2")
    wrapped = _CompatCursor(cur, lastrowid=None)
    assert wrapped.rowcount == cur.rowcount == 1


def test_compat_cursor_synthesises_the_exact_id_key_when_flagged():
    """Exact dict-equality (not `"id" in result`) pins the literal key
    spelling and the stored `had_returning`/`lastrowid` values verbatim."""
    import sqlite3

    from mcp_server.infrastructure.sqlite_compat import _CompatCursor

    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    cur = raw.execute("SELECT id FROM t")  # no rows
    wrapped = _CompatCursor(cur, lastrowid=7, had_returning=True)
    assert wrapped.fetchone() == {"id": 7}


def test_compat_cursor_needs_both_flag_and_lastrowid_to_synthesise():
    """`had_returning AND lastrowid`, not `OR`: a falsy lastrowid (0 here)
    must not synthesise a row even when RETURNING was stripped."""
    import sqlite3

    from mcp_server.infrastructure.sqlite_compat import _CompatCursor

    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    cur = raw.execute("SELECT id FROM t")  # no rows
    wrapped = _CompatCursor(cur, lastrowid=0, had_returning=True)
    assert wrapped.fetchone() is None


def test_executemany_clears_had_returning_and_reports_real_rowcount():
    """Pins the post-executemany field wiring, not just the row output.

    `lastrowid` is asserted `None` too, matching the documented sqlite3
    contract (a cursor's `lastrowid` is only meaningful after a single-row
    `execute()` INSERT, never after `executemany()`
    https://docs.python.org/3/library/sqlite3.html#sqlite3.Cursor.lastrowid)
    — which makes a mutant that hardcodes `self.lastrowid = None` in
    `executemany()` a documented EQUIVALENT mutant here, not a gap: no
    input can make the real `self._cursor.lastrowid` differ from `None`
    after an `executemany()` call, so no test can distinguish them.
    """
    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO t (a) VALUES (%s)", [("x",), ("y",)])
        assert cur.lastrowid is None
        assert cur.rowcount == 2
        assert cur._had_returning is False


def test_connection_execute_computes_had_returning_from_the_actual_sql(
    monkeypatch,
):
    """`PsycopgCompatConnection.execute` must compute `had_returning` from
    the SQL it was actually given, not silently default it away. Forces the
    pre-3.35 strip path (this runtime natively supports RETURNING) and
    asserts the returned cursor synthesises the id — the same contract
    `test_stripped_returning_synthesises_the_insert_id` pins for the
    `cursor()` path, exercised here through `execute()` directly."""
    import mcp_server.infrastructure.sqlite_sql_translate as sqltr

    monkeypatch.setattr(sqltr, "_SUPPORTS_RETURNING", False)

    conn = _compat_conn()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    cur = conn.execute("INSERT INTO t (a) VALUES (%s) RETURNING id", ("x",))
    assert cur.fetchone() == {"id": 1}


def test_executescript_runs_every_statement_verbatim():
    conn = _compat_conn()
    conn.executescript(
        "CREATE TABLE t (id INTEGER PRIMARY KEY); INSERT INTO t (id) VALUES (1);"
    )
    assert conn.execute("SELECT id FROM t").fetchone() == {"id": 1}


def test_enable_load_extension_forwards_the_flag_verbatim():
    """Spies on the wrapped connection: sqlite3 accepts `enable_load_extension
    (None)` silently (it does not raise), so only a spy — not a raised
    exception — can tell a forwarded `False` apart from a hardcoded one."""
    calls = []

    class _FakeRealConn:
        def enable_load_extension(self, enabled):
            calls.append(enabled)

    conn = PsycopgCompatConnection(_FakeRealConn())
    conn.enable_load_extension(True)
    conn.enable_load_extension(False)
    assert calls == [True, False]


# ── The seven handler entry paths (issue #206 acceptance criterion 3) ────


@pytest.mark.asyncio
async def test_extract_inserts_claims(seeded_store):
    from mcp_server.handlers.wiki_extract import handler

    out = await handler({"limit": 50})
    assert out.get("errors") == []
    assert out["claims_inserted"] > 0


@pytest.mark.asyncio
async def test_resolve_links_entities(seeded_store):
    """Guards the `entity_ids = '{}'` defect: this returned 0 forever."""
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_resolve import handler as resolve

    await extract({"limit": 50})
    out = await resolve({"limit": 50})
    assert out["claims_processed"] > 0
    assert out["entity_links_written"] > 0


@pytest.mark.asyncio
async def test_emerge_creates_concepts(seeded_store):
    from mcp_server.handlers.wiki_emerge import handler as emerge
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_resolve import handler as resolve

    await extract({"limit": 50})
    await resolve({"limit": 50})
    out = await emerge({"limit": 50})
    assert out["claims_loaded"] > 0
    assert out["concepts_inserted"] > 0


@pytest.mark.asyncio
async def test_synthesize_creates_drafts(seeded_store):
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_synthesize import handler as synthesize

    await extract({"limit": 50})
    out = await synthesize({"limit": 50})
    assert out.get("errors") == []
    assert out["drafts_created"] > 0


@pytest.mark.asyncio
async def test_compile_publishes_pages(tmp_path, monkeypatch, seeded_store):
    from mcp_server.handlers.wiki_pipeline import handler as pipeline

    monkeypatch.setattr("mcp_server.infrastructure.config.WIKI_ROOT", tmp_path / "wiki")
    out = await pipeline({"limit_per_stage": 50})
    assert out["stages"]["compile"].get("errors") == []
    assert out["pages_published"] > 0


@pytest.mark.asyncio
async def test_refine_lists_pending_drafts(seeded_store):
    """wiki_refine's read path — list_drafts over wiki.drafts on SQLite."""
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_refine import handler_get
    from mcp_server.handlers.wiki_synthesize import handler as synthesize

    await extract({"limit": 50})
    await synthesize({"limit": 50})

    out = await handler_get({"list_pending": True, "limit": 20})
    assert "error" not in out
    assert len(out["drafts"]) > 0
    assert all("title" in d for d in out["drafts"])


@pytest.mark.asyncio
async def test_migrate_reconciles_against_an_empty_tree(tmp_path, sqlite_store):
    from mcp_server.handlers.wiki_migrate import migrate_wiki

    root = tmp_path / "wiki"
    root.mkdir()
    out = migrate_wiki(root, sqlite_store._conn, dry_run=True)
    assert out["pages_processed"] == 0


# ── The pipeline as a whole ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_reports_no_stage_errors(tmp_path, monkeypatch, seeded_store):
    from mcp_server.handlers.wiki_pipeline import handler as pipeline

    monkeypatch.setattr("mcp_server.infrastructure.config.WIKI_ROOT", tmp_path / "wiki")
    out = await pipeline({"limit_per_stage": 50})
    failed = {
        name: stage["error"]
        for name, stage in out["stages"].items()
        if isinstance(stage, dict) and "error" in stage
    }
    assert failed == {}


@pytest.mark.asyncio
async def test_pipeline_produces_pages_not_just_silence(
    tmp_path, monkeypatch, seeded_store
):
    """The success-shaped-payload defect: zeros everywhere and no error."""
    from mcp_server.handlers.wiki_pipeline import handler as pipeline

    monkeypatch.setattr("mcp_server.infrastructure.config.WIKI_ROOT", tmp_path / "wiki")
    out = await pipeline({"limit_per_stage": 50})
    assert out["claims_inserted"] > 0
    assert out["drafts_approved"] > 0
    assert out["pages_published"] > 0

    counts = {
        table: seeded_store._raw_conn.execute(
            f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - fixed literals
        ).fetchone()[0]
        for table in ("wiki_claim_events", "wiki_drafts", "wiki_pages")
    }
    assert all(n > 0 for n in counts.values()), counts


# ── Signal emission (issue #206 acceptance criterion 2) ──────────────────


@pytest.mark.asyncio
async def test_pipeline_stage_failure_is_logged(caplog, monkeypatch):
    """Assert the EMISSION, not a downstream effect (§13.1 F1)."""
    import mcp_server.handlers.wiki_pipeline as wp

    async def boom():
        raise RuntimeError("stage exploded")

    with caplog.at_level(logging.ERROR, logger=wp.__name__):
        label, result = await wp._safe_call("extract", boom())

    assert label == "extract"
    assert result == {"error": "stage exploded"}
    emitted = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert emitted, "a failed stage produced no log record"
    assert "extract" in emitted[0].getMessage()
    assert "stage exploded" in emitted[0].getMessage()


@pytest.mark.asyncio
async def test_backfill_logs_pipeline_failure(caplog, monkeypatch, sqlite_store):
    """A failed pipeline must not stay silent inside backfill_memories.

    Drives the real `_process_imports` clause — the one that used to store
    `{"error": ...}` and return a success-shaped payload with no log line.
    """
    import mcp_server.handlers.backfill_memories as bm

    async def boom(_args=None):
        raise RuntimeError("pipeline exploded")

    # backfill_memories binds the pipeline handler at module top as
    # _pipeline (#197 family 4) — patch the consumer's binding.
    monkeypatch.setattr(bm, "_pipeline", boom)

    async def one_import(*_args, **_kwargs):
        return 1, 0

    monkeypatch.setattr(bm, "_import_file", one_import)
    monkeypatch.setattr(bm, "mark_backfilled", lambda *a, **k: None)

    with caplog.at_level(logging.ERROR, logger=bm.__name__):
        result = await bm._process_imports(
            sqlite_store,
            [(bm.Path("x.jsonl"), "slug", "hash")],
            0.0,
            1,
            0,
            run_pipeline=True,
        )

    # The error is still reported in the payload...
    assert result["pipeline"]["error"] == "pipeline exploded"
    # ...and now it is ALSO emitted as an operator-visible signal.
    emitted = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert emitted, "pipeline failure produced no log record"
    assert "pipeline exploded" in emitted[0].getMessage()
