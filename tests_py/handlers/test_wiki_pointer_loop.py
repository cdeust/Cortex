"""Issue #622 — the page → memory → page loop, end to end on SQLite.

``wiki_write`` writes page P and registers a pointer memory M carrying a
prefix of P's markdown. Before the fix, ``remember`` handed M straight to
``wiki_memory_sync`` → ``wiki_sync.build_from_memory``, which classified
the pointer's own YAML-and-heading text as prose and wrote a second page
P′ under a kind directory no caller asked for (``rfc/_general/`` in the
report), with the frontmatter copied into the body, a ``title:`` line as
the H1, and the body cut mid-word.

The file also pins the second door into the same loop
(``wiki_extract``'s candidate query) and the boundary-safe pointer
truncation. The scan scope that let the stray page survive a purge is in
``test_wiki_purge_scan_scope.py``.

Backend: SQLite, pinned through the real composition root, the way
``test_wiki_pipeline_sqlite.py`` drives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.core import wiki_sync
from mcp_server.handlers import remember, wiki_write
from mcp_server.shared.wiki_layout import PAGE_KINDS
from mcp_server.shared.wiki_pointer import (
    POINTER_CONTENT_MAX_CHARS,
    is_pointer_source,
    pointer_source,
    truncate_on_word_boundary,
)

# The authored page from the report, trimmed to the shape that matters:
# frontmatter whose first body-ish line is a ``title:`` key, a real H1,
# and enough prose to clear the classifier's admission gates. The tag
# ``architecture`` is what admitted the pointer in the report — two
# strays for six writes, because only tagged writes reach the classifier.
_AUTHORED_PAGE = (
    "---\n"
    'title: "Architecture overview: lazarus"\n'
    "kind: explanation\n"
    "domain: lazarus\n"
    "status: seedling\n"
    "audience: [developer]\n"
    "---\n\n"
    "# Architecture overview: lazarus\n\n"
    "Lazarus is a local web application that tracks a sourdough starter. "
    "It runs on a single machine, serves one page, and stores everything "
    "in a SQLite file next to the code. We decided to keep Lazarus "
    "single-process because a broker would double the operational "
    "surface for no measured gain. This page describes the real layers "
    "of the project and the rule that keeps them apart.\n"
)

_AUTHORED_PATH = "explanation/lazarus/architecture-overview.md"
_AUTHORED_TAGS = ["architecture", "lazarus"]


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
    yield get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)

    reset_shared_store()
    get_memory_settings.cache_clear()


@pytest.fixture()
def wiki_root(tmp_path, monkeypatch) -> Path:
    """A throwaway wiki root bound into every module that writes to one."""
    root = tmp_path / "wiki"
    root.mkdir()
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(root))
    monkeypatch.setattr(remember, "WIKI_ROOT", str(root))
    return root


def _pages_on_disk(root: Path) -> list[str]:
    """Every markdown file that sits under a page-kind directory."""
    found = []
    for md in root.rglob("*.md"):
        rel = md.relative_to(root)
        if len(rel.parts) > 1 and rel.parts[0] in PAGE_KINDS:
            found.append(rel.as_posix())
    return sorted(found)


async def _author_the_page() -> dict:
    return await wiki_write.handler(
        {
            "path": _AUTHORED_PATH,
            "content": _AUTHORED_PAGE,
            "mode": "create",
            "tags": _AUTHORED_TAGS,
        }
    )


# ── The loop ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wiki_write_leaves_exactly_the_page_it_was_asked_for(
    sqlite_store, wiki_root
):
    """One wiki_write call, one page. No derived copy of the pointer."""
    result = await _author_the_page()
    assert "error" not in result, result

    assert _pages_on_disk(wiki_root) == [_AUTHORED_PATH]


@pytest.mark.asyncio
async def test_the_pointer_memory_is_still_registered(sqlite_store, wiki_root):
    """Cutting the loop must not cost the page its place in recall.

    Deleting or skipping the pointer is explicitly not the fix: the
    pointer is what surfaces the authored page in ``recall``.
    """
    await _author_the_page()

    with sqlite_store._conn.cursor() as cur:
        cur.execute("SELECT id, content, source FROM memories ORDER BY id")
        rows = cur.fetchall()

    pointers = [r for r in rows if is_pointer_source(r["source"])]
    assert len(pointers) == 1
    assert pointers[0]["source"] == pointer_source(_AUTHORED_PATH)


@pytest.mark.asyncio
async def test_without_the_guard_the_loop_reproduces(
    sqlite_store, wiki_root, monkeypatch
):
    """The counterfactual: neutralise the guard and the stray page returns.

    Without this the two tests above would pass on code that simply
    never admitted the content — this pins that the classifier *would*
    have written a second page, and that the pointer check is what stops
    it.
    """
    monkeypatch.setattr(wiki_sync, "is_pointer_source", lambda _origin: False)

    await _author_the_page()

    derived = [p for p in _pages_on_disk(wiki_root) if p != _AUTHORED_PATH]
    assert derived, "expected the pre-fix stray page to reappear"


# ── The second door: wiki_extract's candidate query ──────────────────────


@pytest.mark.asyncio
async def test_extract_skips_wiki_pointer_memories(sqlite_store):
    """Claims mined from a pointer feed synthesize/compile the same loop."""
    from mcp_server.handlers.wiki_extract import handler as extract

    pointer_id = sqlite_store.insert_memory(
        {
            "content": _AUTHORED_PAGE,
            "domain": "lazarus",
            "source": pointer_source(_AUTHORED_PATH),
        }
    )
    authored_id = sqlite_store.insert_memory(
        {
            "content": (
                "We decided to adopt WRRF fusion over plain RRF because heat "
                "needed weights the flat formula could not carry."
            ),
            "domain": "lazarus",
            "source": "",
        }
    )

    out = await extract({"limit": 50})
    assert out.get("errors") == []
    assert out["claims_inserted"] > 0

    with sqlite_store._conn.cursor() as cur:
        cur.execute("SELECT DISTINCT memory_id FROM wiki.claim_events")
        seen = {r["memory_id"] for r in cur.fetchall()}

    assert pointer_id not in seen
    assert authored_id in seen


@pytest.mark.asyncio
async def test_extract_skips_a_pointer_named_explicitly(sqlite_store):
    """The exclusion holds on the single-memory branch too."""
    from mcp_server.handlers.wiki_extract import handler as extract

    pointer_id = sqlite_store.insert_memory(
        {
            "content": _AUTHORED_PAGE,
            "domain": "lazarus",
            "source": pointer_source(_AUTHORED_PATH),
        }
    )

    out = await extract({"memory_id": pointer_id})
    assert out["memories_processed"] == 0


# ── Defect 4: the mid-word cut ───────────────────────────────────────────


def test_truncate_keeps_whole_words():
    text = "la règle qui garde les couches séparées " * 40
    cut = truncate_on_word_boundary(text, 100)

    assert len(cut) <= 100
    assert cut.endswith("…")
    assert not cut[:-1].endswith(" ")
    # The last word is whole: it also occurs, whole, in the original.
    assert f"{cut[:-1].rsplit(' ', 1)[-1]} " in text


def test_truncate_leaves_short_text_untouched():
    assert truncate_on_word_boundary("short", 100) == "short"


def test_truncate_still_bounds_a_single_long_token():
    token = "x" * 300
    cut = truncate_on_word_boundary(token, 50)

    assert len(cut) <= 50
    assert cut.endswith("…")


@pytest.mark.asyncio
async def test_pointer_memory_content_is_not_cut_mid_word(sqlite_store, wiki_root):
    long_page = _AUTHORED_PAGE + ("Chaque couche reste séparée. " * 60)
    await wiki_write.handler(
        {
            "path": _AUTHORED_PATH,
            "content": long_page,
            "mode": "create",
            "tags": _AUTHORED_TAGS,
        }
    )

    with sqlite_store._conn.cursor() as cur:
        cur.execute("SELECT content FROM memories WHERE source LIKE 'wiki://%'")
        stored = cur.fetchone()["content"]

    assert len(stored) <= POINTER_CONTENT_MAX_CHARS
    assert stored.endswith("…")
    assert long_page.startswith(stored[:-1].rstrip())
