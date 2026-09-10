"""Upserts and queries over wiki.pages / wiki.concepts / wiki.claim_events /
wiki.drafts / wiki.links / wiki.citations / wiki.memos.

Pure infrastructure — no core imports, no handler imports.

source: ADR-0571"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_wiki_claims import (
    delete_claims_for_memory,
    get_claims_by_entity,
    get_claims_for_memory,
    get_entities_by_memory,
    get_entity_name_index,
    insert_claim_events,
    update_claim_entities,
    update_claim_supersedes,
)
from mcp_server.infrastructure.pg_store_wiki_common import body_hash
from mcp_server.infrastructure.pg_store_wiki_concepts import (
    get_concepts_by_entity_overlap,
    insert_concept,
    list_concepts,
    update_concept,
)
from mcp_server.infrastructure.pg_store_wiki_drafts import (
    find_draft_for_source,
    get_draft,
    insert_draft,
    list_drafts,
    update_draft,
    update_draft_status,
)
from mcp_server.infrastructure.pg_store_wiki_links import (
    delete_links_from,
    get_backlinks,
    resolve_unresolved_links,
    upsert_link,
)
from mcp_server.infrastructure.pg_store_wiki_notes import (
    insert_citation,
    insert_memo,
    list_uncited_deliberate_memories,
    wiki_stats,
)
from mcp_server.infrastructure.pg_store_wiki_pages import (
    delete_pages_by_rel_path,
    get_page_by_rel_path,
    get_page_by_slug,
    list_all_rel_paths,
    upsert_page,
)
from mcp_server.infrastructure.pg_store_wiki_sources import upsert_page_sources
from mcp_server.infrastructure.pg_store_wiki_thermo import (
    apply_staleness_decisions,
    apply_thermo_decisions,
    get_claim_file_refs_for_pages,
    list_pages_for_decay,
)

__all__ = [
    "apply_staleness_decisions",
    "apply_thermo_decisions",
    "body_hash",
    "delete_claims_for_memory",
    "delete_links_from",
    "delete_pages_by_rel_path",
    "find_draft_for_source",
    "get_backlinks",
    "get_claim_file_refs_for_pages",
    "get_claims_by_entity",
    "get_claims_for_memory",
    "get_concepts_by_entity_overlap",
    "get_draft",
    "get_entities_by_memory",
    "get_entity_name_index",
    "get_page_by_rel_path",
    "get_page_by_slug",
    "insert_citation",
    "insert_claim_events",
    "insert_concept",
    "insert_draft",
    "insert_memo",
    "list_all_rel_paths",
    "list_concepts",
    "list_drafts",
    "list_pages_for_decay",
    "list_uncited_deliberate_memories",
    "resolve_unresolved_links",
    "update_claim_entities",
    "update_claim_supersedes",
    "update_concept",
    "update_draft",
    "update_draft_status",
    "upsert_link",
    "upsert_page",
    "upsert_page_sources",
    "wiki_stats",
]
