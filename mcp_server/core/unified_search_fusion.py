"""Phase 3 (ADR-0046) — Reciprocal Rank Fusion for unified search.

Merges two (or more) ranked result lists from independent retrievers —
Cortex memory recall and AP code-symbol search — into a single list
ordered by aggregated relevance. RRF is the canonical choice for
fusing heterogeneous retrievers whose scores are not comparable:

    score(d) = sum_{r in retrievers} 1 / (K + rank_r(d))

Source: Cormack, Clarke, Büttcher (2009) "Reciprocal Rank Fusion
Outperforms Condorcet and Individual Rank Learning Methods", SIGIR.

K defaults to 60 per the paper's experimental finding. Cortex already
uses K=60 for WRRF inside ``pg_recall`` (``settings.WRRF_K``), so
Phase 3 is consistent with the rest of the retrieval stack.

Pure logic — no I/O. Each input list is a list of ``{id, ...}`` dicts,
and the output is a re-ranked list enriched with ``rrf_score`` and
``source_ranks`` (per-retriever rank for transparency).
"""

from __future__ import annotations

from typing import Iterable

# Matches ``pg_recall`` default; see Cormack (2009) for the empirical
# basis. Increasing K flattens the rank weight so near-top items of
# different retrievers count roughly the same; decreasing K sharpens
# the top-of-list bias.
DEFAULT_K = 60


def _id_of(item: dict, id_key: str) -> str | None:
    v = item.get(id_key)
    return str(v) if v is not None else None


def fuse(
    ranked_lists: Iterable[tuple[str, list[dict]]],
    *,
    k: int = DEFAULT_K,
    id_key: str = "id",
    top_n: int | None = None,
) -> list[dict]:
    """RRF-merge two or more ranked lists into one.

    ``ranked_lists`` is ``[(source_name, results), ...]``. Each result
    must expose an ``id_key`` field used as the identity for fusion —
    duplicates across lists are collapsed. When a result appears in
    more than one list, the merged record keeps the first-seen body
    but records per-source ranks so the UI can explain *why* it ranked
    where it did.

    Items lacking ``id_key`` are skipped — silently, because a missing
    id means the retriever produced something we can't dedupe safely.

    ``top_n`` clips the returned list to the strongest N. ``None`` keeps
    all items.
    """
    scores: dict[str, float] = {}
    bodies: dict[str, dict] = {}
    source_ranks: dict[str, dict[str, int]] = {}
    source_order: list[str] = []

    for source_name, results in ranked_lists:
        source_order.append(source_name)
        for rank, item in enumerate(results, start=1):
            ident = _id_of(item, id_key)
            if ident is None:
                continue
            delta = 1.0 / (k + rank)
            scores[ident] = scores.get(ident, 0.0) + delta
            if ident not in bodies:
                # First retriever to mention this id owns the body.
                bodies[ident] = {**item}
            source_ranks.setdefault(ident, {})[source_name] = rank

    merged = []
    for ident, score in scores.items():
        body = bodies[ident]
        merged.append(
            {
                **body,
                id_key: ident,
                "rrf_score": round(score, 6),
                "source_ranks": source_ranks[ident],
            }
        )
    merged.sort(key=lambda r: r["rrf_score"], reverse=True)
    # Determinism: ties broken by presence in more retrievers, then by id.
    merged.sort(
        key=lambda r: (-r["rrf_score"], -len(r["source_ranks"]), r[id_key]),
    )
    if top_n is not None and top_n >= 0:
        merged = merged[:top_n]
    _ = source_order  # reserved for future per-source weighting
    return merged


__all__ = ["DEFAULT_K", "fuse"]
