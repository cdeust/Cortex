"""Governance regression for the headless authoring worker (G-1).

Design finding (grooming-continu G-1): the headless worker's two write
sites (``page_io._rewrite_page`` / ``page_io._write_anchor_page``) used
to write markdown bytes straight to disk, bypassing every governance
side effect the interactive ``wiki_write`` MCP tool applies — no
``write_class``, no pointer memory, no ``wiki.citations`` row. These
tests pin the fix: both sites now route through
``wiki_write.write_governed_page`` (the single governed path shared
with the interactive tool), so a headless-authored page produces the
exact same governance artifacts as an interactive one, distinguished
only by the ``headless-authoring`` tag.

Runs against the shared store wired by conftest (live PG / cortex_test
DB — never the real ``cortex`` dev DB, forced by tests_py/conftest.py).
Skips gracefully if no PostgreSQL-backed store is available, matching
the rest of the handler-level test suite's convention.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from mcp_server.handlers.consolidation import page_io
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.observability import silent_failure

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store


def _store():
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("headless-authoring governance test requires a PostgreSQL store")
    return store


def _unique(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


def _fetch_pointer_memory(conn, source: str) -> dict | None:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, content, tags, source, write_class "
            "FROM memories WHERE source = %(source)s ORDER BY id DESC LIMIT 1",
            {"source": source},
        )
        return cur.fetchone()


def _fetch_page_row(conn, rel_path: str) -> dict | None:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, rel_path FROM wiki.pages WHERE rel_path = %(p)s",
            {"p": rel_path},
        )
        return cur.fetchone()


@pytest.fixture(autouse=True)
def _reset_silent_failure():
    silent_failure.reset()
    yield
    silent_failure.reset()


# ── 1. Anchor-page authoring goes through the governed path ────────────────


@pytest.mark.asyncio
async def test_write_anchor_page_produces_governed_pointer_memory(
    tmp_path: Path,
) -> None:
    _pg_only()
    domain = _unique("headlessdom")
    rel_path = f"reference/{domain}/architecture.md"

    written = await page_io._write_anchor_page(
        wiki_root=tmp_path,
        domain=domain,
        scope_name="architecture",
        suggested_kind="reference",
        suggested_path=rel_path,
        body_markdown="This project has a modest architecture.",
        today="2026-07-11",
    )

    assert written == tmp_path / rel_path
    assert written.exists()
    assert written.read_text(encoding="utf-8").startswith("---\n")

    store = _store()
    conn = store._conn
    row = _fetch_pointer_memory(conn, f"wiki://{rel_path}")
    assert row is not None, "governed write must register a wiki pointer memory"
    assert row["write_class"] == "mechanical"
    assert "wiki" in row["tags"]
    assert "headless-authoring" in row["tags"]
    assert "anchor" in row["tags"]

    page_row = _fetch_page_row(conn, rel_path)
    assert page_row is not None, "governed write must sync wiki.pages"


# ── 2. Gap-fill rewrite goes through the governed path ──────────────────────


@pytest.mark.asyncio
async def test_rewrite_page_produces_governed_pointer_memory(tmp_path: Path) -> None:
    _pg_only()
    rel_path = f"reference/{_unique('headlessgap')}/module.md"
    page_path = tmp_path / rel_path
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(
        "---\n"
        "title: Module\n"
        "kind: reference\n"
        "domain: test\n"
        "lifecycle: needs-curation\n"
        "curation_gaps:\n"
        "  - purpose\n"
        "---\n\n"
        "_(missing — needs: What this file is responsible for)_\n",
        encoding="utf-8",
    )

    ok = await page_io._rewrite_page(
        page_path,
        tmp_path,
        new_body="This module resolves widgets.\n",
        new_curation_gaps=[],
    )

    assert ok is True
    new_text = page_path.read_text(encoding="utf-8")
    assert "resolves widgets" in new_text
    assert "lifecycle: draft" in new_text

    store = _store()
    conn = store._conn
    row = _fetch_pointer_memory(conn, f"wiki://{rel_path}")
    assert row is not None
    assert row["write_class"] == "mechanical"
    assert "headless-authoring" in row["tags"]


# ── 3. A failed governed write is observable, not silently dropped ─────────


@pytest.mark.asyncio
async def test_rewrite_page_failure_is_recorded_via_silent_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """When the governed write itself fails, the old code path silently
    swallowed the ``OSError`` and returned ``False`` with zero log signal.
    The fix routes the failure through ``silent_failure.note`` so the
    degraded worker is observable.
    """
    rel_path = "reference/x/module.md"
    page_path = tmp_path / rel_path
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(
        "---\ntitle: X\ncuration_gaps:\n  - purpose\n---\n\nbody\n",
        encoding="utf-8",
    )

    async def _boom(*_a, **_kw):
        return {"error": "simulated governed-write failure"}

    monkeypatch.setattr(page_io, "write_governed_page", _boom)

    ok = await page_io._rewrite_page(
        page_path, tmp_path, new_body="new body", new_curation_gaps=[]
    )

    assert ok is False
    status = silent_failure.status()
    assert "headless_authoring.rewrite_page.governed_write" in status
    assert status["headless_authoring.rewrite_page.governed_write"]["count"] == 1


@pytest.mark.asyncio
async def test_write_anchor_page_failure_is_recorded_via_silent_failure(
    tmp_path: Path, monkeypatch
) -> None:
    async def _boom(*_a, **_kw):
        return {"error": "simulated create-mode race"}

    monkeypatch.setattr(page_io, "write_governed_page", _boom)

    written = await page_io._write_anchor_page(
        wiki_root=tmp_path,
        domain="proj",
        scope_name="architecture",
        suggested_kind="reference",
        suggested_path="reference/proj/architecture.md",
        body_markdown="body",
        today="2026-07-11",
    )

    assert written is None
    status = silent_failure.status()
    assert "headless_authoring.write_anchor_page.governed_write" in status
