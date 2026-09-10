---
title: "ADR-0658 — mcp_server/shared/minhash.py rationale"
status: accepted
source: mcp_server/shared/minhash.py
---

# ADR-0658 — mcp_server/shared/minhash.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Used by the entity-graph fuzzy deduplicator (``core.entity_dedup``) to block
candidate near-duplicate entity labels in sub-quadratic time before the exact
Jaro-Winkler verification pass.
````

## module — original line 7 (docstring)

````text
Sources:
    - MinHash (Jaccard estimation via min-wise permutations):
      Broder, A. (1997). "On the resemblance and containment of documents."
      Compression and Complexity of Sequences (SEQUENCES '97).
    - Band-LSH (banding trades false-positive/false-negative rate against the
      Jaccard threshold): Indyk & Motwani (1998), and Leskovec, Rajaraman &
      Ullman, *Mining of Massive Datasets*, 3rd ed., Ch. 3.
````

## module — original line 15 (docstring)

````text
The hash family (Mersenne-prime affine permutations) and band structure are
equivalent to ``datasketch`` so dedup quality is unchanged, but this module
deliberately avoids ``datasketch``/``scipy``: datasketch.lsh imports
``scipy.integrate.quad`` at module load, whose array_api_compat layer can hang
for minutes under EDR software on some platforms (graphify issue, ported here).
````

## module — original line 21 (docstring)

````text
Pure utility — no I/O, no domain knowledge. Shared layer.

````

## _integrate — original line 77 (docstring)

````text
Left-Riemann numerical integration — replaces scipy.integrate.quad.
````

## inline — original line 31 (comment)

````text
# source: Broder 1997 hash family
````

## module — original line 34 (comment)

````text
# One (a, b) affine-coefficient pair-array per num_perm, shared across instances.
# Seeded deterministically so sketches are reproducible run-to-run.
````

## inline — original line 42 (comment)

````text
# fixed seed → deterministic sketches
````
