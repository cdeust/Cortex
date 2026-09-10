"""Write-class classification — the single choke point for M-D2/M-D3/7.4.

source: ADR-0688"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AUTO = "auto"
DELIBERATE = "deliberate"
DERIVED = "derived"
MECHANICAL = "mechanical"

ALL_WRITE_CLASSES: tuple[str, ...] = (AUTO, DELIBERATE, DERIVED, MECHANICAL)

# source: ADR-0688


_AUTO_SOURCES: frozenset[str] = frozenset({"post_tool_capture"})

# source: ADR-0688


_DERIVED_SOURCES: frozenset[str] = frozenset({"consolidation", "sleep-compute"})
_DERIVED_SOURCE_PREFIXES: tuple[str, ...] = ("cls",)

# source: ADR-0688


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

# source: ADR-0688


NON_DELIBERATE_EXACT_SOURCES: tuple[str, ...] = tuple(
    sorted(_AUTO_SOURCES | _DERIVED_SOURCES | _MECHANICAL_SOURCES)
)
NON_DELIBERATE_SOURCE_PREFIXES: tuple[str, ...] = tuple(
    sorted(_DERIVED_SOURCE_PREFIXES + _MECHANICAL_SOURCE_PREFIXES)
)


def classify_write_class(memory: Mapping[str, Any] | str | None) -> str:
    """Resolve a memory (or a bare source string) to its write class.

    Precondition: memory is a source-bearing mapping, a source string,
    or None.
    Postcondition: returns a member of ALL_WRITE_CLASSES. Unknown or empty
    source resolves to DELIBERATE.
    source: ADR-0688"""
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

    Precondition: value is the caller's raw write_class argument or None.
    Postcondition: returns None for None or a member of ALL_WRITE_CLASSES.
    Otherwise raises ValueError naming the offending value and valid classes.
    This function performs no I/O.
    source: ADR-0688"""
    if value is None:
        return
    if value not in ALL_WRITE_CLASSES:
        raise ValueError(
            f"Invalid write_class {value!r}: must be one of "
            f"{', '.join(ALL_WRITE_CLASSES)} (or omitted, which defaults "
            "to 'deliberate' via source-based fallback classification)."
        )
