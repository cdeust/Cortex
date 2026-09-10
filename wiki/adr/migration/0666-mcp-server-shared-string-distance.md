---
title: "ADR-0666 — mcp_server/shared/string_distance.py rationale"
status: accepted
source: mcp_server/shared/string_distance.py
---

# ADR-0666 — mcp_server/shared/string_distance.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Used by the entity-graph fuzzy deduplicator (``core.entity_dedup``) to verify
MinHash/LSH candidate pairs. ``rapidfuzz`` is intentionally NOT a dependency of
Cortex (graphify used it; we re-implement faithfully with stdlib only), so these
are hand-rolled to the published algorithms.
````

## module — original line 8 (docstring)

````text
Sources:
    - Jaro similarity: Jaro, M. A. (1989). "Advances in record linkage
      methodology." J. Amer. Statist. Assoc. 84(406), 414-420.
    - Winkler prefix boost: Winkler, W. E. (1990). "String comparator metrics
      and enhanced decision rules in the Fellegi-Sunter model of record
      linkage." Proc. Section on Survey Research Methods, ASA, 354-359.
      Standard scaling factor p = 0.1, prefix capped at l = 4.
    - Optimal String Alignment (restricted Damerau-Levenshtein, allows a single
      adjacent transposition per substring): Damerau, F. J. (1964); standard DP
      formulation. Sufficient for the "single-edit" guard in entity_dedup.
````

## module — original line 19 (docstring)

````text
Pure utility — no I/O. Returns are in [0, 1] for similarities, non-negative ints
for distances.

````

## jaro_similarity — original line 64 (docstring)

````text
Jaro similarity in [0, 1] (Jaro 1989).
````

## jaro_winkler_similarity — original line 84 (docstring)

````text
Jaro-Winkler similarity in [0, 1] (Winkler 1990).
````

## osa_distance — original line 104 (docstring)

````text
Optimal String Alignment distance (restricted Damerau-Levenshtein).
````

## module — original line 25 (comment)

````text
# Winkler 1990 standard parameters.
````

## inline — original line 26 (comment)

````text
# source: Winkler 1990, p; rapidfuzz prefix_weight default
````

## inline — original line 27 (comment)

````text
# source: Winkler 1990, l capped at 4
````

## module — original line 92 (comment)

````text
# strict=False: Jaro-Winkler's common-prefix scan is defined for strings
# of differing length (it stops at the shorter one).
````
