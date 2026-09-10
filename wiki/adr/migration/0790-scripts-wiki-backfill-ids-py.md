# ADR-0790: scripts/wiki_backfill_ids.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/wiki_backfill_ids.py`; original SHA-256 `feddcbb0f279154afe94ae9e253398ce7eb046fbdf9928b91999304e0f9210aa`.

## Original docstring, lines 2–30

````text
"""Backfill stable page IDs on every existing wiki page — Phase 3 of ADR-2244.

Walks the methodology wiki and, for each page that lacks a valid
``id`` field in its frontmatter, mints a fresh UUID4 and writes it back
in place. The page body and other frontmatter fields are preserved
verbatim.

Goal: every page has a stable identifier *before* Phase 4 bulk migration
moves pages around. Without it, inbound links into renamed pages rot.
With it, renames can leave redirect stubs (see
``mcp_server.core.wiki_redirect``).

Usage
-----

Dry-run (default) — show counts and a sample of paths::

    python scripts/wiki_backfill_ids.py

Apply the change in place::

    python scripts/wiki_backfill_ids.py --apply

The script is idempotent: re-running after ``--apply`` finds zero
pages needing a backfill (all already have ids). Pages that already
carry a valid ``id`` are skipped, no exceptions. Redirect stub pages
(``redirect_to`` / ``redirect_id`` in frontmatter) are skipped — they
don't need their own identity, they reference another page's.
"""
````

## Original docstring, lines 72–85

````text
"""Add or replace ``id: <page_id>`` inside the frontmatter block.

    Preconditions: ``text`` begins with ``---`` delimited frontmatter.

    Behavior:
      - If an ``id:`` line exists *inside the frontmatter*, replace its
        value with ``page_id``. This handles the malformed-id case
        (e.g. ``id: garbage``) — we overwrite the bad value rather than
        leaving a duplicate key.
      - Otherwise insert ``id: <page_id>`` immediately after the opening
        ``---`` line.

    The body (everything after the closing fence) is untouched.
    """
````

## Reviewed remaining docstring (scripts/wiki_backfill_ids.py, interim lines 2–25)

````text
Backfill stable page IDs on every existing wiki page — Phase 3 of ADR-0790.

Walks the methodology wiki and, for each page that lacks a valid
``id`` field in its frontmatter, mints a fresh UUID4 and writes it back
in place. The page body and other frontmatter fields are preserved
verbatim.

Goal: every page has a stable identifier *before* Phase 4 bulk migration
moves pages around. Without it, inbound links into renamed pages rot.
With it, renames can leave redirect stubs (see
``mcp_server.core.wiki_redirect``).

Usage
-----

Dry-run (default) — show counts and a sample of paths::

    python scripts/wiki_backfill_ids.py

Apply the change in place::

    python scripts/wiki_backfill_ids.py --apply

source: ADR-0790
````

