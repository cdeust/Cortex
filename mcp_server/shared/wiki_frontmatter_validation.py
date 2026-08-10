"""Write-time frontmatter validation/normalization — pure, no I/O.

Closes the corruption class that PR #104 (commit 53712df8) repaired
reactively at read-time inside ``wiki_pages.parse_page`` (dup-label
strip, quote strip). That fix made ``recall``/`wiki_read`` tolerant of
the two corruption signatures already on disk; it did nothing to stop
``write_governed_page`` (``mcp_server/handlers/wiki_write.py``) from
persisting caller-supplied markdown verbatim, so any new signature the
read-time parser doesn't yet know about would still land on disk
uncorrected.

This module round-trips content through ``parse_page`` + ``render_page``
so what reaches disk is ALWAYS the canonical form — whatever
``parse_page`` already knows how to repair is repaired before the first
byte is written, not after. Issue #110 moved the call site of this
function from ``wiki_write.write_governed_page`` down to
``infrastructure.wiki_store.write_page`` itself, so normalization covers
every caller (governed or direct) rather than only the interactive
``wiki_write`` tool path — see that module's docstring for the contract
and ``tests_py/architecture/test_write_page_call_sites.py`` for the
audited list of direct callers. The read-time tolerance
(``wiki_pages.parse_page``'s scalar-branch repair) stays in place
unchanged as defense in depth for content written before this gate
existed.

Deliberately does NOT duplicate ``parse_page``'s parsing state machine —
only the one shape it cannot repair (an unclosed frontmatter fence, which
would silently fold the intended body into misparsed frontmatter keys)
is detected and rejected here.
"""

from __future__ import annotations

from mcp_server.shared.wiki_pages import parse_page, render_page


class UnclosedFrontmatterError(ValueError):
    """Content opens a frontmatter fence (``---``) but never closes it.

    This is the one frontmatter shape ``parse_page`` cannot tolerate:
    with no closing ``---`` line, every subsequent line — including what
    the author intended as body prose — is consumed as a frontmatter
    key/value pair (``parse_page``'s scan loop never finds the ``break``
    condition and keeps assigning ``fm[key] = ...`` for every remaining
    line), silently destroying the body. Every other malformed-but-closed
    shape (duplicated ``<key>: <key>: ...`` label, YAML-quoted scalar,
    empty value) is repaired by ``parse_page``'s existing scalar/list
    branches and is never rejected by this gate.
    """


def _opens_frontmatter_fence(content: str) -> bool:
    """True iff ``content`` begins with a frontmatter fence line.

    Mirrors ``parse_page``'s own opening check (wiki_pages.py) exactly,
    so this gate and the parser agree on what counts as "has frontmatter".
    """
    return content.startswith("---\n") or content.startswith("---\r\n")


def _has_closing_fence(content: str) -> bool:
    """True iff some line after the opening fence is itself exactly ``---``.

    precondition: ``_opens_frontmatter_fence(content)`` is already True.
    postcondition: returns whether ``parse_page`` would find its
    ``body_start`` inside the text (line ~117, wiki_pages.py) rather than
    falling off the end with ``body_start`` still at its ``len(lines)``
    initial value.
    """
    lines = content.splitlines()
    return any(line.strip() == "---" for line in lines[1:])


def normalize_frontmatter(content: str) -> str:
    """Canonicalize a wiki page's frontmatter at write time.

    precondition: ``content`` is the FULL markdown (frontmatter + body,
    or plain body with no frontmatter) a caller intends to persist
    verbatim to the wiki tree — never a partial fragment (the ``append``
    write mode's content is a fragment appended below existing content,
    not a full page, and must not be passed through this function; see
    ``write_governed_page``'s call site).
    postcondition: content carrying no frontmatter fence is returned
    completely unchanged — plain markdown pages are outside this gate's
    concern. Content that opens AND closes a fence is returned as
    ``render_page(parse_page(content))`` — the exact canonical form every
    ``build_*`` template (``wiki_pages.build_adr``/``build_note``/etc.)
    already emits, so a healthy page round-trips byte-identical
    (idempotent) and a corrupted one (duplicated label, stray quotes) is
    repaired before the first byte reaches disk.
    raises: ``UnclosedFrontmatterError`` when content opens a fence with
    no closing ``---`` — the one shape that is structurally inexploitable.
    Every other shape is normalized, never rejected.
    """
    if not _opens_frontmatter_fence(content):
        return content
    if not _has_closing_fence(content):
        raise UnclosedFrontmatterError(
            "frontmatter fence ('---') opened but never closed — refusing "
            "to write: parse_page would silently consume the entire body "
            "as malformed frontmatter keys, destroying it"
        )
    doc = parse_page(content)
    return render_page(doc)


__all__ = ["normalize_frontmatter", "UnclosedFrontmatterError"]
