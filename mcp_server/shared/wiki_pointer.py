"""Wiki pointer memories — recognising a memory that points at a page.

``wiki_write`` and ``wiki_adr`` register one memory per authored page so
the page surfaces in ``recall``. That memory carries a prefix of the
page's own markdown: it is a pointer, never material to build a page
from. Every pass that materialises memories into wiki pages must be able
to recognise one, and the recognition has to key on a signal no
hand-authored memory can carry by accident.

The ``wiki://<rel_path>`` prefix on a memory's origin field is that
signal — only the two pointer writers set it, and it names the page the
memory already points at. Neither of the other two candidate signals is
usable on its own: the tag ``wiki`` is legitimately carried by a memory
*about* the wiki, and ``write_class='mechanical'`` is shared with
seeding, ingestion and backfill writers whose memories are genuine page
material (``backfill_memories``, ``seed_project``, ``ingest_prd``,
``ingest_findings``, ``import_sessions``, ``codebase_analyze``,
``wiki_seed_codebase``).

Closes the page → memory → page loop reported in issue #622.

source: ADR-0475"""

from __future__ import annotations

WIKI_POINTER_SOURCE_PREFIX = "wiki://"

# SQL-side spelling of the same predicate, for handlers that filter
# candidate memories in the database rather than in Python.
WIKI_POINTER_SOURCE_LIKE = f"{WIKI_POINTER_SOURCE_PREFIX}%"

# A pointer carries a prefix of the page, not the page: enough for
# ``recall`` to rank and preview it. Unchanged from the budget
# wiki_write/wiki_adr have applied since the pointer memory existed —
# issue #622 fixed where the cut lands, not how much is kept.
# source: ADR-0475
POINTER_CONTENT_MAX_CHARS = 500

_ELLIPSIS = "…"


def pointer_source(rel_path: str) -> str:
    """The canonical origin value for the pointer memory of ``rel_path``."""
    return f"{WIKI_POINTER_SOURCE_PREFIX}{rel_path}"


def is_pointer_source(value: str | None) -> bool:
    """Whether a memory's origin marks it as a wiki-page pointer.

    Precondition: ``value`` is a memory's stored origin string, or None.
    Postcondition: True only for the ``wiki://`` prefix written by
    ``wiki_write``/``wiki_adr``; never raises.
    """
    return str(value or "").strip().startswith(WIKI_POINTER_SOURCE_PREFIX)


def truncate_on_word_boundary(text: str, limit: int = POINTER_CONTENT_MAX_CHARS) -> str:
    """Cut ``text`` to at most ``limit`` characters without splitting a word.

    Precondition: ``limit`` is greater than the length of the ellipsis.
    Postcondition: the result is at most ``limit`` characters; it either
    is ``text`` unchanged, or ends with a single ellipsis placed at the
    last whitespace boundary that fits. Text with no whitespace inside
    the budget (a single long token) is cut at the budget — there is no
    boundary to honour — and still marked with the ellipsis.
    """
    if len(text) <= limit:
        return text
    head = text[: limit - len(_ELLIPSIS)]
    boundary = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if boundary > 0:
        head = head[:boundary]
    return head.rstrip() + _ELLIPSIS


__all__ = [
    "POINTER_CONTENT_MAX_CHARS",
    "WIKI_POINTER_SOURCE_LIKE",
    "WIKI_POINTER_SOURCE_PREFIX",
    "is_pointer_source",
    "pointer_source",
    "truncate_on_word_boundary",
]
