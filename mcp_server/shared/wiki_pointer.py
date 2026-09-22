"""Wiki pointer memories — recognising a memory that points at a page.

``wiki_write`` and ``wiki_adr`` register one memory per authored page so
the page surfaces in ``recall``. That memory carries a prefix of the
page's own markdown: it is a pointer, never material to build a page
from. Every pass that materialises memories into wiki pages must be able
to recognise one, and the recognition has to key on a signal no
hand-authored memory can carry by accident.

The ``wiki://<rel_path>`` prefix on a memory's ``source`` column is that
signal. Neither of the other two candidate signals is usable on its own:
the tag ``wiki`` is legitimately carried by a memory *about* the wiki,
and ``write_class='mechanical'`` is shared with seeding, ingestion and
backfill writers whose memories are genuine page material
(``backfill_memories``, ``seed_project``, ``ingest_prd``,
``ingest_findings``, ``import_sessions``, ``codebase_analyze``,
``wiki_seed_codebase``).

``wiki://`` is a reserved internal scheme. ``remember``'s public
``source`` parameter enumerates the six values a caller may set
(``session``, ``tool``, ``user``, ``consolidation``, ``import``,
``distillation``) and ``wiki://`` is not among them, so a client that
honours the schema cannot collide with it. A client that ignores the
enum and writes ``wiki://<something>`` anyway is declaring the memory a
page pointer, and is treated as one.

``is_pointer_source`` is the single authority. A SQL pre-filter built by
``not_a_pointer_sql`` narrows a candidate query before it reaches Python,
but it is an optimisation and never the guarantee: LIKE cannot reproduce
``str.strip()``, so the Python predicate, which is the stricter of the
two, runs last on whatever the query returns.

Closes the page → memory → page loop reported in issue #622.

source: ADR-0475"""

from __future__ import annotations

WIKI_POINTER_SOURCE_PREFIX = "wiki://"

# SQL-side spelling of the pre-filter's right-hand side.
WIKI_POINTER_SOURCE_LIKE = f"{WIKI_POINTER_SOURCE_PREFIX}%"

# A pointer carries a prefix of the page, not the page: enough for
# ``recall`` to rank and preview it. Unchanged from the budget
# wiki_write/wiki_adr have applied since the pointer memory existed —
# issue #622 fixed where the cut lands, not how much is kept.
# source: ADR-0475
POINTER_CONTENT_MAX_CHARS = 500

_ELLIPSIS = "…"


def pointer_source(rel_path: str) -> str:
    """The canonical ``source`` value for the pointer memory of ``rel_path``."""
    return f"{WIKI_POINTER_SOURCE_PREFIX}{rel_path}"


def is_pointer_source(value: str | None) -> bool:
    """Whether a memory's ``source`` marks it as a wiki-page pointer.

    Precondition: ``value`` is a memory's stored ``source`` column, or
    None.
    Postcondition: True only for the reserved scheme followed by a
    non-empty path — the shape ``pointer_source`` produces. A bare
    ``wiki://`` names no page and is not a pointer. Surrounding
    whitespace is ignored, so a value a migration or a hand-written row
    padded still resolves the same way. Never raises.
    """
    stripped = str(value or "").strip()
    if not stripped.startswith(WIKI_POINTER_SOURCE_PREFIX):
        return False
    return len(stripped) > len(WIKI_POINTER_SOURCE_PREFIX)


def not_a_pointer_sql(column: str) -> tuple[str, tuple[str, ...]]:
    """SQL fragment excluding pointer rows, plus its bound params.

    Follows the fragment-builder convention of
    ``infrastructure/pg_scope_clause.py``: the predicate text and its
    single bind param are built in one place so they cannot drift apart
    between call sites.

    Precondition: ``column`` is a qualified column reference the caller
    controls (a literal in its own module), never caller input.
    Postcondition: returns a parenthesised predicate that is true for
    every row ``is_pointer_source`` would admit, and may also be true for
    a padded pointer value LIKE cannot see. It narrows, it does not
    decide — callers apply ``is_pointer_source`` to the rows they get.
    """
    return f"({column} IS NULL OR {column} NOT LIKE %s)", (WIKI_POINTER_SOURCE_LIKE,)


def truncate_on_word_boundary(text: str, limit: int = POINTER_CONTENT_MAX_CHARS) -> str:
    """Cut ``text`` to at most ``limit`` characters without splitting a word.

    Precondition: ``limit`` leaves room for the ellipsis; a smaller one
    cannot mark the cut and raises ValueError rather than returning a
    string that silently overruns or loses the marker.
    Postcondition: the result is at most ``limit`` characters; it either
    is ``text`` unchanged, or ends with a single ellipsis placed at the
    last whitespace boundary that fits. Text with no whitespace inside
    the budget (a single long token) is cut at the budget — there is no
    boundary to honour — and still marked with the ellipsis.
    """
    if limit <= len(_ELLIPSIS):
        raise ValueError(
            f"limit must exceed the ellipsis width ({len(_ELLIPSIS)}); got {limit}"
        )
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
    "not_a_pointer_sql",
    "pointer_source",
    "truncate_on_word_boundary",
]
