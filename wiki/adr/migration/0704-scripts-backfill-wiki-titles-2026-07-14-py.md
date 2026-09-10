# ADR-0704: scripts/backfill_wiki_titles_2026_07_14.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/backfill_wiki_titles_2026_07_14.py`; original SHA-256 `e5f15e864db8dc4d31ffcb31ee196c377955b84cc602acb66bb610f5fb375bcb`.

## Original docstring, lines 1–41

````text
"""One-shot migration: repair wiki.pages.title corrupted by the parse_page
frontmatter-scalar bug fixed in mcp_server/core/wiki_pages.py (2026-07-14).

Root cause: parse_page's scalar branch (1) never stripped surrounding
quote characters from a YAML-quoted value, and (2) never stripped a
duplicated "<key>: " label an LLM-authored page's own frontmatter echoed
into its value (e.g. on-disk file content literally
``title: title: "Public API surface: ai-architect-mcp-codebase"``). Both
defects are fixed and covered by tests_py/core/test_wiki_pages.py
(test_parse_page_strips_quoted_scalar_value,
test_parse_page_strips_duplicated_key_label).

This script targets ONLY rows whose title still carries one of these two
corruption signatures (`title LIKE 'title:%'` or `title LIKE '"%"'`) and
re-derives the title from the CURRENT on-disk file via the same
`page_row_from_md` the live wiki_write/wiki_migrate path uses — not a
duplicated parser.

Why not just re-run `wiki_migrate`: `upsert_page`'s UPDATE is gated on
`body_hash <> EXCLUDED.body_hash` (pg_store_wiki_pages.py) — a body-hash
optimization that correctly skips no-op writes for unchanged file
content. Because the corrupted title was derived from an unchanged file
body (only the DERIVATION changed, not the file), that gate silently
skips exactly the rows this migration must fix. This script performs a
direct, explicitly-scoped `UPDATE ... SET title = %s WHERE id = %s`
for the affected id set only — it does not touch any other column and
does not run for rows outside the corruption signature.

Usage:
    DATABASE_URL=postgresql://cdeust@localhost:5432/cortex \\
        python3 scripts/backfill_wiki_titles_2026_07_14.py [--dry-run]

Precondition: a CSV backup of (id, rel_path, title) for every affected
row has already been taken (see the task's
wiki-titles-backup.csv artifact) before this script is run with
--dry-run absent.
Postcondition: every wiki.pages row matched by the corruption signature
at start-of-run either (a) has its title replaced by the value
`page_row_from_md` derives from the current on-disk file, or (b) is
reported as "source file missing" and left untouched (never guessed).
"""
````

## Reviewed remaining docstring (scripts/backfill_wiki_titles_2026_07_14.py, interim lines 1–23)

````text
One-shot migration: repair wiki.pages.title corrupted by the parse_page
frontmatter-scalar bug fixed in mcp_server/core/wiki_pages.py (2026-07-14).

This script targets ONLY rows whose title still carries one of these two
corruption signatures (`title LIKE 'title:%'` or `title LIKE '"%"'`) and
re-derives the title from the CURRENT on-disk file via the same
`page_row_from_md` the live wiki_write/wiki_migrate path uses — not a
duplicated parser.

Usage:
    DATABASE_URL=postgresql://cdeust@localhost:5432/cortex \
        python3 scripts/backfill_wiki_titles_2026_07_14.py [--dry-run]

Precondition: a CSV backup of (id, rel_path, title) for every affected
row has already been taken (see the task's
wiki-titles-backup.csv artifact) before this script is run with
--dry-run absent.
Postcondition: every wiki.pages row matched by the corruption signature
at start-of-run either (a) has its title replaced by the value
`page_row_from_md` derives from the current on-disk file, or (b) is
reported as "source file missing" and left untouched (never guessed).

source: ADR-0704
````

