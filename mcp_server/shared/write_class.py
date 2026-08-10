"""Write-class classification — the single choke point for M-D2/M-D3/7.4.

Design doc: ``scratchpad/memoire-qui-comprend-design.md`` §M-D2 (taxonomy
table) + §M-D3 (homeostatic stratification, this module's first consumer).

**Why this module exists.** Two independent M-series decisions need to know
"what kind of write is this memory" without disagreeing with each other:
M-D3 (7.1) stratifies homeostatic regulation by class; M-D2/7.4 gates the
write path itself by class. Both MUST resolve the same memory to the same
class, or the write gate and the homeostat argue about the population
they're each regulating. ``classify_write_class`` is therefore THE single
contract — every writer classifies through this function, never a
parallel predicate.

**7.4 (this increment): the explicit column is real.** ``memories.write_class``
now exists (migration in ``infrastructure/pg_schema.py``). Every internal
writer (hooks, consolidation passes, ingestion pipelines) sets it
explicitly at write time — the writer KNOWS what it is; inference from
``source`` text is no longer the primary path for live writes. Two things
remain true by design, not by accident:

1. ``classify_write_class``'s explicit-column-wins check (below) is now
   the *live* fast path for every writer that sets ``write_class``, not
   just a forward-compat stub.
2. Source-string inference is demoted to a FALLBACK, used only when a
   caller genuinely omits ``write_class`` (e.g. an external MCP caller
   that didn't ask for a specific class — the safe default is
   ``deliberate``) and by the one-shot historical backfill
   (``handlers/consolidation/write_class_backfill.py``) that classifies
   pre-7.4 rows which never had an explicit column at all. This is ONE
   function serving both roles — never two classification paths.

**Strict validation is a separate, stricter function** — ``validate_write_class``.
``classify_write_class`` stays permissive (silently ignores a garbage
explicit value and falls back to source-inference) because it is also
called by read-time/maintenance code (``homeostatic.py``) against
arbitrary historical rows, where crashing on unexpected data would be a
regression. ``validate_write_class`` is for the write-time contract (the
``remember`` MCP tool and any direct writer): it raises a plain
``ValueError`` — translated to ``mcp_server.errors.ValidationError`` by
the composition-root handler, per the Clean Architecture dependency rule
that core/ must not import errors/ — on any non-``None`` value outside
``ALL_WRITE_CLASSES``, so a caller's typo is reported, never silently
reclassified.

Taxonomy (M-D2 table, extended 7.4 with the writers this increment wires
explicitly — see module-level source-set comments below for the measured
DB source values each class covers):

| Class       | Determination (source)                                    |
|-------------|------------------------------------------------------------|
| auto        | ``post_tool_capture``                                      |
| deliberate  | NOT IN (post_tool_capture, codebase_analyze, seed, ingest,  |
|             | cls, consolidation, sleep-compute, wiki://) — i.e.          |
|             | everything not otherwise listed; also the explicit default  |
|             | for a `remember` MCP call that omits `write_class`          |
| derived     | ``consolidation`` (memify_derive) + ``cls*`` (CLS semantic  |
|             | promotion) + ``sleep-compute`` (dream-replay auto-narration)|
|             | — same rationale: machine-synthesized from the              |
|             | consolidation/replay pipeline, not user intent; idempotence |
|             | markers judge duplication, not novelty                      |
| mechanical  | backfill/ingest/seed/codebase_analyze/wiki-pointer-sync —    |
|             | one-shot bulk import or structural-indexing passes, not an  |
|             | ongoing population                                          |

Pure logic. No I/O, no DB access — a classification is a projection of
data already in hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AUTO = "auto"
DELIBERATE = "deliberate"
DERIVED = "derived"
MECHANICAL = "mechanical"

ALL_WRITE_CLASSES: tuple[str, ...] = (AUTO, DELIBERATE, DERIVED, MECHANICAL)

# source == post_tool_capture is the ONLY auto-capture pathway (audit,
# core/write_post_store.py::_AUTO_CAPTURE_SOURCES — same set, re-exported
# here rather than imported to keep this module dependency-free; the two
# are documented as required to move together).
_AUTO_SOURCES: frozenset[str] = frozenset({"post_tool_capture"})

# "consolidation" is memify_derive's exact source value
# (handlers/consolidation/memify_derive.py:245). Sources beginning with
# "cls" (cls-consolidation, measured: 59 rows in dev DB) are CLS semantic
# promotion — a second machine-synthesis pathway out of the consolidation
# pipeline, sharing derived's rationale (idempotence-judged, not
# novelty-judged; see M-D2's "derived" row justification).
# "sleep-compute" (handlers/consolidation/sleep.py::_store_narration) is a
# third: dream-replay auto-narration, same machine-synthesis rationale —
# added 7.4 (inventory of every direct `store.insert_memory` writer that
# bypasses the `remember` gate found this pathway had no explicit class,
# silently falling to DELIBERATE under the old source-only inference).
_DERIVED_SOURCES: frozenset[str] = frozenset({"consolidation", "sleep-compute"})
_DERIVED_SOURCE_PREFIXES: tuple[str, ...] = ("cls",)

# Bulk/one-shot ingestion pathways (audit, core/source_monitoring.py::
# _EXTERNAL_PATHWAYS is the closest existing precedent set; this list adds
# codebase_analyze and generalizes the seed/ingest family, matching the
# M-D2 table's "mechanical" row and measured DB source values: backfill:*
# (prefix, one entry per scanned directory), seed_project, ingest_codebase).
_MECHANICAL_SOURCES: frozenset[str] = frozenset(
    {
        "codebase_analyze",
        "seed_project",
        "seed",
        "ingest_codebase",
        "ingest_prd",
        "ingest_findings",
        "ingest",
        "import",
        "import_sessions",
    }
)
# "backfill:<slug>" (per-directory backfill), "seed:<rel>"
# (wiki_seed_codebase.py, one memory per seeded file — a bulk pass
# distinct from seed_project's stage source), "ingest_codebase:docs"
# (ingest_docs_content_writers.py, docs-specific variant of
# ingest_codebase), and "wiki://<rel_path>" (the protected pointer
# memories wiki_write.py/wiki_adr.py register for recall — structural
# indexing bookkeeping, not user-authored content) — all added 7.4 from
# the same direct-writer inventory as _DERIVED_SOURCES above.
_MECHANICAL_SOURCE_PREFIXES: tuple[str, ...] = (
    "backfill:",
    "seed:",
    "ingest_codebase:",
    "wiki://",
)

# SQL-side mirror of "everything NOT deliberate" (auto | derived |
# mechanical), exported for pg_store_memory_reheat.py::
# list_deliberate_below_target — the other DB-facing call site besides
# homeostatic._apply_fold's AUTO_SOURCE_VALUES above. INC7.2 root-cause
# fix: that query used to carry its OWN hardcoded exact-match tuple
# ("seed", "ingest", "cls") that never matched the real DB values
# ("seed_project", "ingest_codebase", "cls-consolidation" — a PREFIX
# family, not an exact string) — a second, silently-diverged
# classification path that let mechanical/derived rows through the
# "deliberate" filter undetected. Exporting the exact-match and prefix
# sets here instead means there is exactly ONE place the taxonomy is
# defined; the SQL predicate cannot drift from ``classify_write_class``'s
# verdict again because it is built from the same frozensets.
NON_DELIBERATE_EXACT_SOURCES: tuple[str, ...] = tuple(
    sorted(_AUTO_SOURCES | _DERIVED_SOURCES | _MECHANICAL_SOURCES)
)
NON_DELIBERATE_SOURCE_PREFIXES: tuple[str, ...] = tuple(
    sorted(_DERIVED_SOURCE_PREFIXES + _MECHANICAL_SOURCE_PREFIXES)
)


def classify_write_class(memory: Mapping[str, Any] | str | None) -> str:
    """Resolve a memory (or a bare source string) to its write class.

    Precondition: ``memory`` is a mapping carrying at least a ``source``
        key (memory row shape from ``_normalize_memory_row`` / any
        ``remember()`` payload), a bare source string, or ``None``.
    Postcondition: return value is one of ``ALL_WRITE_CLASSES``. Unknown
        or empty source resolves to ``DELIBERATE`` — the safe default:
        an unclassified write is never assumed to be flood/noise, so it
        is never subject to fold-style regulation (matches the doctrine
        this module exists to enforce — see module docstring).

    Explicit-column-wins (7.4, live): if ``memory`` carries an explicit
    ``write_class`` value in ``ALL_WRITE_CLASSES``, it wins outright —
    this is the primary path for every writer that sets it (see module
    docstring). An explicit value OUTSIDE ``ALL_WRITE_CLASSES`` is
    deliberately NOT an error here — this function stays permissive
    because ``homeostatic.py`` and the one-shot backfill call it against
    arbitrary/historical rows where raising would be a regression; it
    silently falls through to source-based inference instead. Callers
    that must reject an invalid explicit value (the ``remember`` MCP
    tool and any direct writer) call ``validate_write_class`` FIRST, at
    the write-time contract boundary — see that function's docstring.
    """
    if memory is None:
        source = ""
    elif isinstance(memory, str):
        source = memory
    else:
        explicit = memory.get("write_class")
        if explicit in ALL_WRITE_CLASSES:
            return str(explicit)
        source = memory.get("source") or ""

    s = str(source).strip()
    if s in _AUTO_SOURCES:
        return AUTO
    if s in _DERIVED_SOURCES or s.startswith(_DERIVED_SOURCE_PREFIXES):
        return DERIVED
    if s in _MECHANICAL_SOURCES or s.startswith(_MECHANICAL_SOURCE_PREFIXES):
        return MECHANICAL
    return DELIBERATE


def validate_write_class(value: str | None) -> None:
    """Reject an explicit ``write_class`` argument that isn't one of the
    four known classes — the write-time contract for every public writer.

    Precondition: ``value`` is the raw ``write_class`` argument as received
        from a caller (MCP tool argument or an internal writer's explicit
        kwarg) — ``None`` when the caller omitted it.
    Postcondition: returns ``None`` (no exception) when ``value`` is
        ``None`` or a member of ``ALL_WRITE_CLASSES``. Raises
        ``ValueError`` with a message naming the offending value and the
        four valid classes otherwise — mandate (user, 2026-07-11): an
        explicit parameter is VALIDATED, never silently reinterpreted.
        Pure logic — no I/O; core/ must not import errors/ (Clean
        Architecture dependency rule), so this raises plain ``ValueError``
        and the composition-root handler (``handlers/remember.py``)
        re-raises it as ``mcp_server.errors.ValidationError``.

    Distinct from ``classify_write_class``: that function is a permissive
    classifier used at read-time against arbitrary/historical data (an
    invalid value there falls back to source-inference, never raises).
    This function is the strict write-time gate — call it BEFORE
    ``classify_write_class`` at every public write entry point.
    """
    if value is None:
        return
    if value not in ALL_WRITE_CLASSES:
        raise ValueError(
            f"Invalid write_class {value!r}: must be one of "
            f"{', '.join(ALL_WRITE_CLASSES)} (or omitted, which defaults "
            "to 'deliberate' via source-based fallback classification)."
        )
