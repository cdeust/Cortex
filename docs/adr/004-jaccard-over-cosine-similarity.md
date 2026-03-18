# ADR-004: Jaccard Similarity Over Cosine Similarity

## Status
Accepted

## Context
Need a set overlap metric for comparing keyword sets between sessions (entry point classification, domain clustering). Must work without a corpus-wide vocabulary or term frequency data.

## Decision
Use Jaccard similarity (`|A∩B| / |A∪B|`) instead of cosine similarity for keyword-level comparisons.

## Consequences
- **Gain**: Simpler implementation (set intersection/union). No TF-IDF computation needed. No vocabulary construction. Intuitive interpretation: 0 = no overlap, 1 = identical sets.
- **Lose**: Ignores term frequency — a keyword appearing 10 times is treated the same as one appearing once. Less discriminating than cosine for longer documents.
- **Neutral**: Sufficient for keyword-level matching where sets are small (5-30 terms). Performance difference is negligible at this scale.

## References
- Jaccard, P. "The Distribution of the Flora in the Alpine Zone" (1912)
- Leskovec, J. et al. "Mining of Massive Datasets" — Chapter 3: Finding Similar Items (2014)
