"""Persist wiki evidence and lifecycle transitions against real PostgreSQL."""

from datetime import datetime, timezone

import pytest

from mcp_server.core.wiki_staleness import StalenessDecision
from mcp_server.core.wiki_thermodynamics import HeatDecision
from mcp_server.infrastructure import pg_store_wiki_claims as claims
from mcp_server.infrastructure import pg_store_wiki_drafts as drafts
from mcp_server.infrastructure import pg_store_wiki_links as links
from mcp_server.infrastructure import pg_store_wiki_pages as pages
from mcp_server.infrastructure import pg_store_wiki_thermo as thermo
from tests_py.conftest import _TEST_DB_URL, _USE_PG

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires PostgreSQL")


@pytest.fixture
def store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    instance = PgMemoryStore(database_url=_TEST_DB_URL)

    # Wiki tables are outside conftest's common table cleanup.
    def clear_wiki():
        with instance.acquire_batch() as conn:
            conn.execute("DELETE FROM wiki.drafts")
            conn.execute("DELETE FROM wiki.claim_events")
            conn.execute("DELETE FROM wiki.pages")

    try:
        clear_wiki()
        yield instance
    finally:
        try:
            clear_wiki()
        finally:
            instance.close()


def _page(conn, name, **fields):
    return pages.upsert_page(
        conn,
        {
            "rel_path": f"{name}.md",
            "slug": name,
            "kind": "concept",
            "title": name,
            "body": name,
            **fields,
        },
    )[0]


def test_decay_eligibility_and_updates_are_idempotent(store):
    with store.acquire_batch() as conn:
        active = _page(conn, "active")
        area = _page(conn, "area", lifecycle_state="area")
        archived = _page(conn, "archived", lifecycle_state="archived")
        _page(conn, "evergreen", lifecycle_state="evergreen")
        assert [r["id"] for r in thermo.list_pages_for_decay(conn)] == [active, area]
        assert [
            r["id"] for r in thermo.list_pages_for_decay(conn, include_archived=True)
        ] == [active, area, archived]
        assert [r["id"] for r in thermo.list_pages_for_decay(conn, limit=1)] == [active]
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        decision = HeatDecision(
            area, 0.05, "archived", True, timestamp, "test transition"
        )
        assert thermo.apply_thermo_decisions(conn, []) == 0
        assert thermo.apply_thermo_decisions(conn, [decision]) == 1
        row = conn.execute("SELECT * FROM wiki.pages WHERE id = %s", (area,)).fetchone()
        assert row["heat"] == pytest.approx(0.05)
        assert row["lifecycle_state"] == "archived"
        assert row["archived_at"] == timestamp
        tended = row["tended"]
        assert thermo.apply_thermo_decisions(conn, [decision]) == 0
        assert (
            conn.execute(
                "SELECT tended FROM wiki.pages WHERE id = %s", (area,)
            ).fetchone()["tended"]
            == tended
        )
        no_change = StalenessDecision(active, [], [], False, False, False, "unchanged")
        stale = StalenessDecision(
            area, ["gone.py"], ["gone.py"], True, False, True, "missing"
        )
        assert thermo.apply_staleness_decisions(conn, []) == 0
        assert thermo.apply_staleness_decisions(conn, [no_change, stale]) == 1
        assert (
            conn.execute(
                "SELECT is_stale FROM wiki.pages WHERE id = %s", (area,)
            ).fetchone()["is_stale"]
            is True
        )


def test_claim_link_updates_exclusions_and_file_refs_round_trip(store):
    memory = store.insert_memory({"content": "claim evidence"})
    first = store.insert_entity({"name": "first", "type": "concept"})
    second = store.insert_entity({"name": "second", "type": "concept"})
    short = store.insert_entity({"name": "xy", "type": "concept"})
    store.insert_memory_entity(memory, first)
    with store.acquire_batch() as conn:
        page = _page(conn, "claim", memory_id=memory)
        assert claims.insert_claim_events(conn, []) == []
        original, revised = claims.insert_claim_events(
            conn,
            [
                {
                    "memory_id": memory,
                    "text": "old",
                    "entity_ids": [first],
                    "evidence_refs": [
                        {"kind": "file", "target": "b.py"},
                        {"kind": "url", "target": "https://example.test"},
                    ],
                },
                {
                    "memory_id": memory,
                    "text": "new",
                    "entity_ids": [first, second],
                    "evidence_refs": [
                        {"kind": "file", "target": "a.py"},
                        {"kind": "file", "target": "b.py"},
                    ],
                },
            ],
        )
        assert claims.get_entities_by_memory(conn, []) == {}
        assert claims.get_entities_by_memory(conn, [memory]) == {memory: [first]}
        index = claims.get_entity_name_index(conn)
        assert index == {"first": first, "second": second}
        assert short not in index.values()
        assert claims.get_claims_by_entity(conn, []) == {}
        grouped = claims.get_claims_by_entity(
            conn, [first, second], exclude_claim_ids=[original]
        )
        assert {key: [r["id"] for r in rows] for key, rows in grouped.items()} == {
            first: [revised],
            second: [revised],
        }
        assert claims.update_claim_entities(conn, []) == 0
        assert claims.update_claim_entities(conn, [(original, [second])]) == 1
        assert claims.update_claim_entities(conn, [(original, [second])]) == 0
        assert claims.update_claim_supersedes(conn, []) == 0
        assert claims.update_claim_supersedes(conn, [(revised, original)]) == 1
        assert claims.update_claim_supersedes(conn, [(revised, original)]) == 0
        rows = claims.get_claims_for_memory(conn, memory)
        assert [r["id"] for r in rows] == [original, revised]
        assert rows[0]["entity_ids"] == [second]
        assert rows[1]["supersedes"] == original
        assert thermo.get_claim_file_refs_for_pages(conn, []) == {}
        assert thermo.get_claim_file_refs_for_pages(conn, [page]) == {
            page: ["a.py", "b.py"]
        }
        assert claims.delete_claims_for_memory(conn, memory) == 2
        assert claims.get_claims_for_memory(conn, memory) == []


def test_page_upsert_preserves_identity_and_delete_only_requested_paths(store):
    with store.acquire_batch() as conn:
        first = _page(conn, "first")
        second = _page(conn, "second")
        same = {
            "rel_path": "first.md",
            "slug": "first",
            "kind": "concept",
            "title": "first",
            "body": "first",
        }
        assert pages.upsert_page(conn, same) == (first, False)
        assert pages.upsert_page(
            conn, {**same, "body": "revised", "title": "revised"}
        ) == (first, True)
        assert set(pages.list_all_rel_paths(conn)) == {"first.md", "second.md"}
        assert pages.delete_pages_by_rel_path(conn, []) == []
        assert pages.delete_pages_by_rel_path(conn, ["first.md", "absent.md"]) == [
            {"id": first, "rel_path": "first.md"}
        ]
        assert pages.list_all_rel_paths(conn) == ["second.md"]
        assert (
            conn.execute(
                "SELECT title FROM wiki.pages WHERE id = %s", (second,)
            ).fetchone()["title"]
            == "second"
        )


def test_unresolved_links_resolve_when_target_appears_and_delete_by_source(store):
    with store.acquire_batch() as conn:
        source = _page(conn, "source")
        links.upsert_link(conn, source, "target")
        assert links.resolve_unresolved_links(conn) == 0
        target = _page(conn, "target")
        assert links.resolve_unresolved_links(conn) == 1
        links.upsert_link(conn, source, "target")
        backlinks = links.get_backlinks(conn, target)
        assert len(backlinks) == 1
        assert backlinks[0]["src_page_id"] == source
        assert backlinks[0]["src_title"] == "source"
        assert links.resolve_unresolved_links(conn) == 0
        assert links.delete_links_from(conn, target) == 0
        assert links.delete_links_from(conn, source) == 1
        assert links.get_backlinks(conn, target) == []


def test_draft_patch_round_trip_and_status_transitions_preserve_publication(store):
    memory = store.insert_memory({"content": "draft source"})
    with store.acquire_batch() as conn:
        page = _page(conn, "published")
        identity = drafts.insert_draft(
            conn, {"title": "before", "kind": "concept", "memory_id": memory}
        )
        other = drafts.insert_draft(
            conn, {"title": "other", "kind": "procedure", "status": "rejected"}
        )
        assert drafts.get_draft(conn, -1) is None
        assert drafts.update_draft(conn, identity) is False
        assert drafts.update_draft(conn, -1, title="missing") is False
        assert (
            drafts.update_draft(
                conn,
                identity,
                title="after's title",
                lead="lead",
                sections=[{"title": "step"}],
                frontmatter={"domain": "sql"},
                confidence=0.75,
                synth_prompt="prompt",
                synth_model="test",
            )
            is True
        )
        row = drafts.get_draft(conn, identity)
        assert row["title"] == "after's title"
        assert row["lead"] == "lead"
        assert row["sections"] == [{"title": "step"}]
        assert row["frontmatter"] == {"domain": "sql"}
        assert row["confidence"] == 0.75
        assert (row["synth_prompt"], row["synth_model"]) == ("prompt", "test")
        assert [
            r["id"] for r in drafts.list_drafts(conn, status="pending", kind="concept")
        ] == [identity]
        assert {r["id"] for r in drafts.list_drafts(conn)} == {identity, other}
        assert drafts.find_draft_for_source(conn) is None
        assert drafts.find_draft_for_source(conn, memory_id=memory)["id"] == identity
        with pytest.raises(ValueError, match="invalid status"):
            drafts.update_draft_status(conn, identity, status="unknown")
        assert (
            drafts.update_draft_status(
                conn, identity, status="published", published_page_id=page
            )
            is True
        )
        assert drafts.update_draft_status(conn, identity, status="approved") is True
        row = drafts.get_draft(conn, identity)
        assert row["published_page_id"] == page
        assert row["reviewed_at"] is not None
        assert row["status"] == "approved"
