"""Community detection and centrality for the codebase dependency graph.

Split from codebase_graph.py to stay under the 300-line limit and to give
community/centrality analysis a single cohesive home (SRP).

Community detection uses the Leiden algorithm when leidenalg+igraph are
installed, falling back to Louvain (networkx) otherwise. Leiden is a strict
improvement over Louvain: it guarantees well-connected communities, which
Louvain does not.

Sources:
- Traag, V.A., Waltman, L., van Eck, N.J. (2019). "From Louvain to Leiden:
  guaranteeing well-connected communities." Scientific Reports 9:5233.
- Blondel et al. (2008). "Fast unfolding of communities in large networks."
  J. Stat. Mech. P10008. (Louvain fallback.)
- Freeman, L.C. (1977). "A set of measures of centrality based on
  betweenness." Sociometry 40(1):35-41.
- Page, L. et al. (1999). "The PageRank Citation Ranking." Stanford InfoLab.
- Riel, A.J. (1996). Object-Oriented Design Heuristics, Ch. 3 — the
  "god class" anti-pattern (a single node coordinating disproportionately
  many others).
"""

from __future__ import annotations

# source: structural — a graph needs at least two nodes before community
# partitioning or centrality ranking is meaningful
_MIN_NODES_FOR_GRAPH_ANALYSIS = 2
# source: structural — standard deviation needs at least two samples
_MIN_SAMPLES_FOR_STD = 2


def _build_dependency_graph(
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
) -> object:
    """Build a weighted networkx graph from file and call edges."""
    import networkx as nx  # noqa: PLC0415 — optional dependency ([codebase] extra); imported where used so environments without it keep working

    g = nx.Graph()
    for src, tgt in file_edges:
        g.add_edge(src, tgt, weight=1.0)
    for src, _, tgt in call_edges:
        if g.has_edge(src, tgt):
            g[src][tgt]["weight"] += 0.5
        else:
            g.add_edge(src, tgt, weight=0.5)
    return g


def _leiden_partition(g: object) -> dict[str, int] | None:
    """Partition g with the Leiden algorithm, or None if deps are absent.

    Implements Traag et al. (2019) via the authors' reference library
    (leidenalg) over an igraph copy of g. Modularity objective for parity
    with the Louvain fallback. seed=42 for determinism.
    """
    try:
        import igraph  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        import leidenalg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None

    nodes = list(g.nodes())  # type: ignore[attr-defined]
    index = {n: i for i, n in enumerate(nodes)}
    edges = [(index[u], index[v]) for u, v in g.edges()]  # type: ignore[attr-defined]
    weights = [g[u][v]["weight"] for u, v in g.edges()]  # type: ignore[index]
    ig = igraph.Graph(n=len(nodes), edges=edges)
    partition = leidenalg.find_partition(
        ig,
        leidenalg.ModularityVertexPartition,
        weights=weights,
        seed=42,
    )
    return {nodes[i]: partition.membership[i] for i in range(len(nodes))}


def detect_communities(
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
) -> dict[str, int]:
    """Detect functional communities on the import+call graph.

    Prefers Leiden (Traag et al. 2019); falls back to Louvain (Blondel
    et al. 2008) when leidenalg+igraph are not installed.

    Returns:
        Map of file_path -> community_id.
    """
    try:
        import networkx as nx  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return {}

    g = _build_dependency_graph(file_edges, call_edges)
    if g.number_of_nodes() < _MIN_NODES_FOR_GRAPH_ANALYSIS:
        return {n: 0 for n in g.nodes()}

    leiden = _leiden_partition(g)
    if leiden is not None:
        return leiden

    communities = nx.community.louvain_communities(g, weight="weight", seed=42)
    result: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node in community:
            result[node] = idx
    return result


def compute_centrality(
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
) -> dict[str, dict[str, float]]:
    """Compute per-node centrality on the dependency graph.

    Returns a map of file_path -> {degree, betweenness, pagerank}, each a
    normalized score in [0, 1]. Empty dict when networkx is unavailable or
    the graph has fewer than 2 nodes.

    Sources: Freeman (1977) betweenness; Page et al. (1999) PageRank;
    Freeman (1979) degree centrality.
    """
    try:
        import networkx as nx  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return {}

    g = _build_dependency_graph(file_edges, call_edges)
    if g.number_of_nodes() < _MIN_NODES_FOR_GRAPH_ANALYSIS:
        return {}

    degree = nx.degree_centrality(g)
    betweenness = nx.betweenness_centrality(g, weight="weight", normalized=True)
    pagerank = nx.pagerank(g, weight="weight")
    return {
        node: {
            "degree": degree.get(node, 0.0),
            "betweenness": betweenness.get(node, 0.0),
            "pagerank": pagerank.get(node, 0.0),
        }
        for node in g.nodes()
    }


def detect_god_nodes(
    centrality: dict[str, dict[str, float]],
    sigma: float = 2.0,
) -> list[str]:
    """Flag "god" nodes: degree-centrality statistical outliers.

    A node is a god node when its degree centrality exceeds
    mean + sigma*std across all nodes — an architectural coordinator that
    couples to disproportionately many others (Riel 1996, god-class
    heuristic). The threshold is measured from the graph itself, not a
    hardcoded coupling count.

    sigma defaults to 2.0 — the two-sigma convention for outlier detection
    (~97.7th percentile under a normal distribution; the empirical/"three
    sigma" rule, Pukelsheim 1994, "The Three Sigma Rule," The American
    Statistician 48(2):88-91).

    Returns the god-node file paths sorted by descending degree centrality.
    """
    if len(centrality) < _MIN_SAMPLES_FOR_STD:
        return []

    degrees = [c["degree"] for c in centrality.values()]
    mean = sum(degrees) / len(degrees)
    variance = sum((d - mean) ** 2 for d in degrees) / len(degrees)
    std = variance**0.5
    if std == 0.0:
        return []

    threshold = mean + sigma * std
    gods = [node for node, scores in centrality.items() if scores["degree"] > threshold]
    return sorted(gods, key=lambda n: centrality[n]["degree"], reverse=True)
