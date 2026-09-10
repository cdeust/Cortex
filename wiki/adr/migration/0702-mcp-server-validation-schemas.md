---
title: "ADR-0702 — mcp_server/validation/schemas.py rationale"
status: accepted
source: mcp_server/validation/schemas.py
---

# ADR-0702 — mcp_server/validation/schemas.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## _check_array_envelope — original line 211 (docstring)

````text
    Source: ADR-0045 R2 (fragility sweep E4) — bounded envelopes on all
    array inputs prevent pathological memory / indexing blowups.
    
````

## module — original line 78 (comment)

````text
# ADR-0045 R2/R5 (fragility sweep v3.13.0 E3):
# content maxLength tightened from 50_000 → 10_000 chars.
# Taleb audit: a 100 KB content blob triggered ~100K fallback
# regex scans in entity extraction plus OOM on the knowledge
# graph path. 10 K is the bounded envelope; callers submitting
# larger content get a ValidationError and must split upstream.
````

## module — original line 85 (comment)

````text
# ADR-0045 R2 (fragility sweep v3.13.0 E4):
# Bounded tags envelope — at most 20 tags, each ≤ 80 chars.
# Prevents a caller from submitting a 10K-element tag list
# (each tag becomes a tsvector lexeme, an FTS dictionary
# entry, and a row in memory_entities) which would blow up
# indexing cost without bounded benefit.
````

## module — original line 121 (comment)

````text
# maxItems mirrors handlers/why.py _MAX_RECEIPT_IDS (bounded
# envelope, ADR-0045 R2; SQLITE_MAX_VARIABLE_NUMBER floor).
````
