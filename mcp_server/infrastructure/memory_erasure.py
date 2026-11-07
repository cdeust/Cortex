"""Hard forget: erase every stored copy of one memory, in one transaction.

A memory's text is copied, at write time or later, into rows that do not
cascade from ``memories``: compression archives (no foreign key), wiki claims,
drafts, citations and compiled pages (``ON DELETE SET NULL``), prospective
triggers and rules mined from it (``source_memory_id``, no key), injection
receipts, stage transitions, and the entities extracted from its text. This
module lists them once for both backends; the store mixins run the list inside
one transaction, so a failure erases nothing and is raised.

What can only run after the commit (SQLite's WAL truncation, removing page
files and artifacts) cannot undo it: a failure there is recorded in
``ErasureReport.residue`` and ``complete`` turns False, so the caller reports
a deleted memory with residue instead of an error that reads as "nothing was
erased" (review of PR #775, N4).

Entities are removed only when they were extracted from text
(``origin = 'text_concept'``), were linked to this memory and to no other: a
code symbol or a concept another memory still cites is kept.

A wiki page compiled or promoted from the memory is a copy of its text and is
removed, row and file, unless the memory is itself a pointer at an authored
page (the page is then the source, the memory the copy).

source: ADR-1111"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")

# (report key, statement); every statement takes the memory id once.
# source: ADR-1111 — table list from pg_schema.py / sqlite_schema*.py
DERIVED_ROWS: tuple[tuple[str, str], ...] = (
    ("archives", "DELETE FROM memory_archives WHERE original_memory_id = %s"),
    ("claims", "DELETE FROM wiki.claim_events WHERE memory_id = %s"),
    ("drafts", "DELETE FROM wiki.drafts WHERE memory_id = %s"),
    ("citations", "DELETE FROM wiki.citations WHERE memory_id = %s"),
    ("prospective", "DELETE FROM prospective_memories WHERE source_memory_id = %s"),
    ("rules", "DELETE FROM memory_rules WHERE source_memory_id = %s"),
    ("receipt_items", "DELETE FROM injection_receipt_items WHERE memory_id = %s"),
    ("stage_transitions", "DELETE FROM stage_transitions WHERE memory_id = %s"),
)

_ORPHAN_TEXT_ENTITIES = (
    "SELECT e.id FROM entities e "
    "JOIN memory_entities me ON me.entity_id = e.id "
    "WHERE me.memory_id = %s AND e.origin = 'text_concept' "
    "AND NOT EXISTS (SELECT 1 FROM memory_entities o "
    "WHERE o.entity_id = e.id AND o.memory_id <> %s)"
)


@dataclass
class ErasureReport:
    """What one hard forget removed; ``page_paths`` are wiki files to delete."""

    deleted: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    page_paths: list[str] = field(default_factory=list)
    fts_method: str = ""
    # SQLite only: False when another connection's snapshot kept the WAL from
    # being truncated (its old frames go at the next checkpoint); None on PG
    wal_truncated: bool | None = None
    # post-commit steps that failed: {"step": name, "error": message}
    residue: list[dict[str, str]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when the rows are gone and no copy is known to remain."""
        return self.deleted and not self.residue and self.wal_truncated is not False

    def after_commit(self, step: str, run: Callable[[], T], failed: T) -> T:
        """Run a step that follows the commit; a failure becomes residue."""
        try:
            return run()
        except Exception as exc:  # noqa: BLE001 — the commit happened; the failure is reported in the result, not raised
            self.residue.append({"step": step, "error": f"{type(exc).__name__}: {exc}"})
            return failed


def _count(cursor: Any) -> int:
    return max(int(getattr(cursor, "rowcount", 0) or 0), 0)


def erase_derived_rows(conn: Any, memory_id: int, report: ErasureReport) -> None:
    for key, statement in DERIVED_ROWS:
        report.counts[key] = _count(conn.execute(statement, (memory_id,)))


def erase_pages(conn: Any, memory_id: int, report: ErasureReport) -> None:
    rows = conn.execute(
        "SELECT rel_path FROM wiki.pages WHERE memory_id = %s", (memory_id,)
    ).fetchall()
    report.page_paths = [r["rel_path"] for r in rows]
    report.counts["pages"] = _count(
        conn.execute("DELETE FROM wiki.pages WHERE memory_id = %s", (memory_id,))
    )


def erase_entities(conn: Any, memory_id: int, report: ErasureReport) -> None:
    rows = conn.execute(_ORPHAN_TEXT_ENTITIES, (memory_id, memory_id)).fetchall()
    ids = [r["id"] for r in rows]
    relationships = 0
    for entity_id in ids:
        relationships += _count(
            conn.execute(
                "DELETE FROM relationships "
                "WHERE source_entity_id = %s OR target_entity_id = %s",
                (entity_id, entity_id),
            )
        )
    conn.execute("DELETE FROM memory_entities WHERE memory_id = %s", (memory_id,))
    for entity_id in ids:
        conn.execute("DELETE FROM entities WHERE id = %s", (entity_id,))
    report.counts["entities"] = len(ids)
    report.counts["relationships"] = relationships
