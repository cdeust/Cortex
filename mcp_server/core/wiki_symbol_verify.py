"""Phase 2 (ADR-0046) — pure staleness verdict for wiki pages over AST.

Complements ``wiki_staleness`` (file-existence check) with a symbol-
existence check: a page that cites ``foo.Bar.baz`` is *symbol-stale*
when that qualified name no longer resolves in AP's code graph.

This module owns the verdict; the handler owns the AP calls. The split
keeps core I/O-free and testable without mocks.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pages with fewer than this many qualname references are exempt from
# the symbol-stale signal — one stray dotted reference is not enough
# evidence. Matches the rationale of ``wiki_staleness.MIN_FILE_REFS``.
MIN_SYMBOL_REFS = 3

# A page is symbol-stale when this fraction of its references cannot be
# resolved in AP. 0.5 matches ``wiki_staleness.STALE_THRESHOLD`` so the
# two signals fire at the same evidence level.
STALE_THRESHOLD = 0.5


@dataclass(frozen=True)
class SymbolStalenessDecision:
    """Per-page symbol-staleness verdict."""

    page_id: int | str
    symbol_refs: list[str]
    missing_refs: list[str]
    is_symbol_stale_now: bool
    is_symbol_stale_was: bool
    transitioned: bool
    rationale: str


def evaluate_symbol_staleness(
    *,
    page_id: int | str,
    is_symbol_stale_was: bool,
    symbol_refs: list[str],
    existence: dict[str, bool],
) -> SymbolStalenessDecision:
    """Decide whether a wiki page is symbol-stale.

    Inputs:
      page_id               — page key (row id or wiki path)
      is_symbol_stale_was   — prior flag, for transition detection
      symbol_refs           — qualnames the page cites (see
                              ``wiki_symbol_extract.harvest_page_symbols``)
      existence             — {qualname: True if AP resolved it}

    A page is stale iff:
      - len(symbol_refs) >= MIN_SYMBOL_REFS, AND
      - missing / total   >= STALE_THRESHOLD.

    The verdict is deterministic — given the same inputs it always
    returns the same output — which lets the handler re-run it after
    any AST change without coordinating state.
    """
    if len(symbol_refs) < MIN_SYMBOL_REFS:
        return SymbolStalenessDecision(
            page_id=page_id,
            symbol_refs=symbol_refs,
            missing_refs=[],
            is_symbol_stale_now=False,
            is_symbol_stale_was=is_symbol_stale_was,
            transitioned=is_symbol_stale_was,  # un-staling counts
            rationale=(f"too few symbol refs ({len(symbol_refs)} < {MIN_SYMBOL_REFS})"),
        )
    missing = [q for q in symbol_refs if not existence.get(q, False)]
    fraction = len(missing) / len(symbol_refs)
    is_now = fraction >= STALE_THRESHOLD
    return SymbolStalenessDecision(
        page_id=page_id,
        symbol_refs=symbol_refs,
        missing_refs=missing,
        is_symbol_stale_now=is_now,
        is_symbol_stale_was=is_symbol_stale_was,
        transitioned=is_now != is_symbol_stale_was,
        rationale=(
            f"{len(missing)}/{len(symbol_refs)} symbols missing "
            f"({fraction * 100:.0f}% — threshold "
            f"{int(STALE_THRESHOLD * 100)}%)"
        ),
    )


__all__ = [
    "MIN_SYMBOL_REFS",
    "STALE_THRESHOLD",
    "SymbolStalenessDecision",
    "evaluate_symbol_staleness",
]
