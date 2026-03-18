# ADR-003: Felder-Silverman Model for Cognitive Profiling

## Status
Accepted

## Context
Need a validated multi-dimensional model for categorizing cognitive style from observable coding behaviors. The model must have empirical backing and map to dimensions that are detectable in session history (tool usage, iteration patterns, exploration vs. exploitation).

## Decision
Use Felder-Silverman learning style dimensions:
- **Active/Reflective** — Does the developer try things immediately or plan first?
- **Sensing/Intuitive** — Concrete examples vs. abstract patterns?
- **Sequential/Global** — Step-by-step vs. big-picture-first?

Supplement with categorical classifiers (debugging style, planning approach) that don't fit a continuous scale.

## Consequences
- **Gain**: Well-validated model with decades of research in engineering education. Dimensions map naturally to observable coding behaviors. Multi-dimensional (avoids reductive single-axis models).
- **Lose**: Original model designed for classroom pedagogy, not software development. Some dimensions (Visual/Verbal) don't map well to CLI-based coding and are omitted.
- **Neutral**: Scores are continuous [-1, 1] which allows nuanced profiles rather than binary buckets.

## References
- Felder, R.M. & Silverman, L.K. "Learning and Teaching Styles in Engineering Education" (1988)
- Felder, R.M. & Soloman, B.A. "Index of Learning Styles" (1991)
