"""Composition root: promote a stored memory to an authored wiki page.

``sync_memory_strict``/``sync_memory`` keep their pre-move names and
contracts — moved, not rewritten — so callers (``handlers.remember``)
and their tests need only an import-path change, not a behavior change.

source: ADR-0462"""

from __future__ import annotations

from pathlib import Path

from mcp_server.core.wiki_sync import build_from_memory
from mcp_server.infrastructure import wiki_reindex_io, wiki_store
from mcp_server.observability import silent_failure


def sync_memory_strict(
    root: Path | str,
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
    domain: str = "",
) -> str | None:
    """Strict variant of ``sync_memory`` — surfaces errors to the caller.

        Preconditions:
            - ``content`` is a non-empty string.
            - ``memory_id`` has already been committed to the store.

        Postconditions:
            - On success: returns the relative path of the written wiki page.
            - On classifier rejection: returns None (not an error — the memory
              did not qualify for a wiki page).
            - On I/O or classifier failure: raises the underlying exception.
              The caller must decide whether the memory write + wiki failure
              constitutes a partial failure.

        Does NOT swallow the reindex failure either — reindex is best-effort
        by design (see ``wiki_reindex_io.try_reindex``), but the page write
        itself must succeed or be reported.

    source: ADR-0462"""
    built = build_from_memory(
        memory_id=memory_id, content=content, tags=tags, domain=domain
    )
    if built is None:
        return None
    rel_path, markdown = built
    wiki_store.write_page(root, rel_path, markdown, mode="replace")
    wiki_reindex_io.try_reindex(Path(root))
    return rel_path


def sync_memory(
    root: Path | str,
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
    domain: str = "",
) -> str | None:
    """Promote a stored memory to a wiki page if it passes the classifier.

        Returns the relative path of the written page, or None when the
        memory is rejected or on error.

    source: ADR-0462"""
    try:
        return sync_memory_strict(
            root,
            memory_id=memory_id,
            content=content,
            tags=tags,
            domain=domain,
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("wiki_memory_sync.sync_memory", exc)
        return None
