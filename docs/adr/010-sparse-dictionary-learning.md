# ADR-010: Sparse Dictionary Learning for Behavioral Features

## Status
Accepted

## Context
Anthropic's 2025 mechanistic interpretability research (Sparse Autoencoders, Circuit Tracing) decomposes neural activations into sparse, interpretable features. Our methodology-agent decomposes behavioral session data into cognitive patterns. We need a principled approach to extract interpretable behavioral features from session data without external dependencies.

## Decision
Use greedy dictionary learning (simplified K-SVD) with Orthogonal Matching Pursuit (OMP) sparse coding on a 27-dimensional behavioral activation space. Each session is represented by tool ratios (7), keyword densities (4), temporal signals (5), derived signals (1), and category scores (10). Sessions are encoded as at most 3 dictionary atoms (sparsity S=3), making features interpretable.

For <10 sessions (cold start), fall back to a static seed dictionary of 8 canonical behavioral features.

## Consequences
- **Gain**: Interpretable behavioral features that can be named, compared across domains, and used for drift detection. Structural parallel to Anthropic's dictionary learning approach.
- **Gain**: O(N·S·K·D) ≈ O(243K) complexity for 200 sessions — under 1 second. No matrix libraries needed — OMP with S=3 uses Cramer's rule for the 3×3 solve.
- **Lose**: Greedy K-SVD is less optimal than the full alternating least-squares K-SVD. Acceptable for our data volume and latency requirements.
- **Neutral**: Zero external dependencies — pure Node.js linear algebra and sparse vector operations.
