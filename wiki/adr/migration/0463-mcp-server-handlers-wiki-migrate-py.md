# ADR-0463: mcp_server/handlers/wiki_migrate.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_migrate.py`; original SHA-256 `59796f5bbbcf260ccdff13e0a89f19769c4112c337bd77181f0fc982fafc5926`.

## Original docstring, lines 1–31

````text
"""Wiki filesystem → DB migration + ghost reconciliation (Phase 1.2 of
redesign, extended for FS<->PG parity).

One-shot idempotent job: walk ~/.claude/methodology/wiki/, parse every
.md file, upsert into wiki.pages, then resolve [[slug]] references
into wiki.links. A fourth pass reconciles wiki.pages against the same
filesystem scan: any row whose rel_path no longer exists on disk (file
deleted, renamed, or purged by wiki_purge — which only ever touches the
FS, never PG) is a "ghost" and is deleted from wiki.pages, cascading via
FK ON DELETE CASCADE to wiki.links and wiki.page_sources (see
pg_schema.py — src_page_id/page_id both CASCADE).

Coverage: PAGE_KINDS-listed directories only (adr/conventions/
explanation/guides/how-to/lessons/notes/reference/rfc/runbook/specs/
tutorial). The `_`-prefixed directories (_kinds/_rules/_views/
_bibliography/_dashboards) and the root README.md are outside
``list_pages``'s scan entirely — they were never upserted, so they can
never appear as ghosts either. No separate exclusion list is needed:
the existence criterion for both phases (upsert, purge) is identical —
"does list_pages() return this rel_path right now".

Re-running is safe — body_hash guards against redundant upsert writes;
the purge phase re-computes ghosts from scratch every run (no state to
go stale).

Invoked as an MCP tool (`wiki_migrate`) or via `python -m
mcp_server.handlers.wiki_migrate [--dry-run]`. Never raises; returns a
summary. dry_run defaults to True (report-only) — matching wiki_purge's
apply=False default — because purging is destructive and this tool is
now exposed over MCP for the first time.
"""
````

## Original comment, lines 61–62

````text
# source: structural — a "kind/domain/page.md" relative path has three
# components; shorter paths carry no domain segment
````

## Original docstring, lines 173–180

````text
"""Build an upsert_page payload from a parsed markdown file.

    Public (no leading underscore): reused by ``wiki_write`` (INC6.8,
    I6-D7) to sync a freshly-written page into ``wiki.pages``
    synchronously instead of waiting for the next ``wiki_migrate``
    sweep — a citation row needs a resolvable ``page_id`` immediately
    after the write, not after the next batch migration.
    """
````

## Original comment, lines 205–207

````text
# ADR-0051 STEP 2: extract every legacy documented-file form
    # (documents:/source_file_path:/file:/file:<path> tag) into the
    # canonical list. documents_primary is the 1:1 fast-path scalar.
````

## Original docstring, lines 261–265

````text
"""Return the subset of ``ids`` that actually exist in the memories table.

    Filenames carry the original memory_id, but those rows may have been
    purged. Avoid FK violations by dropping unknown ids before insert.
    """
````

## Original comment, lines 427–434

````text
# dry_run must be transactionally neutral end-to-end: passes 1-3
    # (upsert_page, delete_links_from/upsert_link, resolve_unresolved_links) write
    # through the same `conn` as pass 4 and have no dry_run gate of their own —
    # only pass 4 checks dry_run internally (see
    # purge_ghost_pages). Committing unconditionally here previously made
    # `--dry-run` persist passes 1-3 despite the name (issue #105). Roll
    # back everything this call wrote when dry_run is requested; commit
    # only on a real (dry_run=False) run.
````

