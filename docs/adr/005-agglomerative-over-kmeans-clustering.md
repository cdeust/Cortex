# ADR-005: Agglomerative Clustering Over K-Means

## Status
Accepted

## Context
Need to cluster first messages from sessions into entry point patterns (e.g., "bug fix", "new feature", "refactor"). The number of clusters k is not known in advance and varies by user.

## Decision
Use agglomerative (hierarchical) clustering with Jaccard similarity and a merge threshold of 0.3. Clusters are built bottom-up by merging the most similar pair until no pair exceeds the threshold.

## Consequences
- **Gain**: No need to specify k. Deterministic results. Threshold is intuitive (0.3 = 30% keyword overlap to merge). Naturally handles varying numbers of entry point types.
- **Lose**: O(n³) time complexity. Not suitable for large n. However, n is typically <100 sessions per domain, making this acceptable.
- **Neutral**: Produces a dendrogram that could be useful for visualization but is currently discarded after cutting.

## References
- Murtagh, F. & Contreras, P. "Algorithms for Hierarchical Clustering: An Overview" (2012)
- Müllner, D. "Modern Hierarchical, Agglomerative Clustering Algorithms" (2011)
