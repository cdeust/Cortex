# ADR-0371: mcp_server/handlers/consolidation/page_io.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/page_io.py`; original SHA-256 `b21ec60398995c4ebc8fbc996db4c64179e6df86cc2732e4f011333132d8ed25`.

## Original docstring, lines 1–10

````text
"""Filesystem read/write helpers for the headless authoring worker.

Pure I/O leaf helpers: read source files, parse/rewrite wiki page
frontmatter, render a project tree, and build the anchor-page prompt
(which reads README/manifest/CLAUDE.md from disk). Split out of
``headless_authoring`` to keep that module under the size limit
(Fowler: Move Function). The public import surface remains
``headless_authoring``; these names are imported there and by the
drain/orchestration siblings.
"""
````

## Original comment, lines 25–28

````text
# Tag attached to every pointer memory the headless worker's writes produce,
# distinguishing them from interactively-authored wiki_write calls in
# recall/audit without changing write_class semantics (both paths share the
# same governed pointer-memory contract — see write_governed_page).
````

## Original comment, lines 36–39

````text
# Cap on a single source file's text handed to the LLM: larger files are
# truncated to head + tail with a "[truncated]" marker (see use site).
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 227–231

````text
# This worker only ever rebuilds a page via
        # _compute_rewritten_page, which always emits a closed fence —
        # this branch is unreachable in practice but the write-time
        # gate (issue #107) makes the failure mode explicit rather than
        # letting an unhandled exception crash the batch drain cycle.
````

## Original comment, lines 458–467

````text
# 'seedling' — the only valid page_row_from_md/wiki.pages.status value
        # for freshly-authored, unreviewed content (CHECK constraint:
        # 'seedling'|'budding'|'evergreen', pg_schema.py). The template used
        # to say 'living', a maturity value the schema has never accepted —
        # invisible before this fix because the raw disk-write path never
        # called page_row_from_md/upsert_page at all (see write_governed_page
        # in wiki_write.py). Root-cause fix, not a cosmetic rename: an
        # invalid status silently degrades the wiki.pages sync to a no-op
        # (best-effort try/except in _sync_page_and_cite), which would have
        # defeated this very governance fix for every anchor page.
````

## Original comment, lines 486–491

````text
# The frontmatter block above is always closed by this function's
        # own literal "---\n\n" — unreachable in practice, but this call
        # runs under asyncio.gather(return_exceptions=False) (see below),
        # so an unhandled exception here would crash sibling anchor-page
        # writes too. Catching keeps the write-time gate (issue #107)
        # from becoming a new way for one page to take the batch down.
````

## Original comment, lines 495–500

````text
# Covers both the mkdir/write OSError the raw path used to swallow
        # AND a create-mode race (page authored concurrently) — both are
        # now observable via silent_failure instead of a bare ``except
        # OSError: return None``. This runs under
        # asyncio.gather(return_exceptions=False), so the caller relies on
        # the None return (not an exception) to skip this one page.
````

## Reviewed remaining docstring (mcp_server/handlers/consolidation/page_io.py, interim lines 405–416)

````text
Write the authored anchor page through the governed wiki-write path.

precondition: ``suggested_path`` is wiki-root-relative and does not yet
exist (callers only reach here for ``covered=False`` scopes).
postcondition: on success, the page exists on disk AND the same
write_class='mechanical' pointer memory + wiki.citations sync as any
other governed write fire (see ``write_governed_page``); on failure
(including a create-mode race where the page now exists), the failure
is recorded via ``silent_failure.note`` and ``None`` is returned —
the previous raw ``OSError``-swallow is replaced with an observable
degradation.
````

