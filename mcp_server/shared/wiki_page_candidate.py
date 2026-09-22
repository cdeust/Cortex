"""The memory fields the wiki materialisation pass reads, as one value.

``build_from_memory`` and ``sync_memory_strict`` each need five facts
about a stored memory to decide whether it becomes a page and where the
page lands. Passing them as five parameters puts both functions over the
four-parameter cap in coding-standards.md §4.4, whose stated remedy is
exactly this: the missing data type.

Bundling them also removes the swap hazard the loop fix introduced.
``memory_source`` is the ``memories.source`` column — the writing
pipeline that produced the row, which ``shared.wiki_pointer`` reads to
recognise a wiki-page pointer. It is NOT ``capture_origin`` /
``resolved_origin``, the separate axis ``remember`` derives from
``origin_tool``; both are short strings and would pass for each other in
a positional call. Here each field is named after the column it carries
and the dataclass is keyword-only, so a swap has to be written out in
full to happen.

source: ADR-0314"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class PageCandidate:
    """A stored memory offered to the wiki as a page.

    Precondition: ``memory_id`` names a row already committed to the
    store, and ``memory_source`` is that row's ``source`` column — the
    empty string when it has none, never a placeholder standing in for
    an unknown value, which would defeat the pointer check.
    """

    memory_id: int | str
    content: str
    memory_source: str
    tags: list[str] | None = None
    domain: str = ""


__all__ = ["PageCandidate"]
