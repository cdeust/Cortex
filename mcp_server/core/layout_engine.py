"""CPU layout engine for the workflow graph.

Pure logic: takes a list of node ids + an edge list, returns a list of
``(node_id, x, y)`` triples. Calls ``igraph`` (MIT, prebuilt PyPI
wheels for macOS/Linux/Windows) for the actual layout. No I/O, no
PostgreSQL imports — this module is testable with synthetic graphs.

Algorithm choice — DrL (Distributed Recursive Layout):
  * O(N log N) per iteration, scales linearly with edge count.
  * Tuned for force-directed exploratory views; produces well-separated
    clusters even on 1M-node graphs in under 3 minutes on a modern CPU.
  * Falls back to Fruchterman-Reingold for tiny graphs (<200 nodes)
    where DrL's bookkeeping overhead is wasted.

Reference: Martin et al. "OpenOrd: An Open-Source Toolbox for Large
Graph Layout", SPIE 2011 — DrL is the OpenOrd algorithm under its
original name.
"""

from __future__ import annotations

import hashlib
from typing import Iterable


def topology_fingerprint(node_ids: Iterable[str], edges: Iterable[tuple]) -> str:
    """Stable fingerprint of the graph's topology, used as a cache key.

    A graph's layout is valid as long as the same set of node ids and
    the same set of (source, target) pairs are present. The
    fingerprint is a SHA-256 over the sorted concatenation; two builds
    with the same topology — even with different memory contents —
    share a fingerprint and reuse the same coords.
    """
    h = hashlib.sha256()
    for nid in sorted(node_ids):
        h.update(nid.encode("utf-8"))
        h.update(b"\n")
    h.update(b"--edges--\n")
    edge_strs = sorted(f"{s}\x00{t}" for s, t in edges)
    for e in edge_strs:
        h.update(e.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def layout(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    *,
    algorithm: str = "drl",
    seed: int = 0,
) -> list[tuple[str, float, float]]:
    """Compute (x, y) per node and return ``[(id, x, y), ...]``.

    Raises:
        ImportError: if ``igraph`` is not installed (the optional
            ``viz-tile`` extra). The caller is expected to surface this
            as a 503 on the HTTP endpoint.
        ValueError: if ``node_ids`` is empty.
    """
    try:
        import igraph as ig
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "igraph is required for layout — install the 'viz-tile' extra: "
            "pip install neuro-cortex-memory[viz-tile]"
        ) from exc

    if not node_ids:
        raise ValueError("layout requires at least one node id")

    # Build an integer-indexed igraph from the string ids. ``igraph``'s
    # vertex API accepts string names but the layout algorithms operate
    # on contiguous integer indices, so we pre-translate.
    idx_of = {nid: i for i, nid in enumerate(node_ids)}
    edge_pairs = [
        (idx_of[s], idx_of[t])
        for s, t in edges
        if s in idx_of and t in idx_of and s != t
    ]
    g = ig.Graph(n=len(node_ids), edges=edge_pairs, directed=False)
    g.simplify()

    if algorithm == "drl" and len(node_ids) >= 200:
        coords = g.layout("drl")
    elif algorithm == "fr" or len(node_ids) < 200:
        coords = g.layout_fruchterman_reingold(niter=200, seed=seed)
    else:
        # Defensive default: DrL is the expected path; fall back to FR
        # for any unknown algorithm name rather than raising.
        coords = g.layout("drl")

    raw = list(coords.coords)
    if not raw:
        return []

    # Normalise into [-1, 1] world coords (the tile renderer + the
    # client coordinate system both assume this range).
    xs = [p[0] for p in raw]
    ys = [p[1] for p in raw]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    span = max(span_x, span_y) * 0.55  # slight padding inside [-1, 1]
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    return [
        (node_ids[i], (raw[i][0] - cx) / span, (raw[i][1] - cy) / span)
        for i in range(len(node_ids))
    ]
