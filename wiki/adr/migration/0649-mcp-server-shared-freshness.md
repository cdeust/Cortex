---
title: "ADR-0649 — mcp_server/shared/freshness.py rationale"
status: accepted
source: mcp_server/shared/freshness.py
---

# ADR-0649 — mcp_server/shared/freshness.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 1 (docstring)

````text
Freshness annotation for injected memories (fleet-watch #110).
````

## module — original line 3 (docstring)

````text
The harness-comparison rev.2 A/B measured the ai-architect stack (Harness B)
serving facts "2-4 months stale with no age signal": every recalled memory
entered the model's context as bare text, so a fresh fact and a months-old one
were indistinguishable. This module renders the freshness the store *already*
tracks -- ``created_at``, the ``source_attribution`` provenance grade, and
``is_stale`` -- as a compact suffix the injection formatters append per memory.
````

## module — original line 10 (docstring)

````text
Pure: a memory dict plus an explicit ``now`` in, an annotation string out. The
caller owns the clock, so the output is deterministic and testable. A memory
that carries none of the three signals yields "" -- callers append nothing, so
bare-memory call sites are unaffected.

````

## module — original line 20 (comment)

````text
# Calendar/SI time-unit boundaries, in seconds. These are unit *definitions*
# (a minute is 60 s, a day 86400 s), not tuned parameters; month and year use
# the conventional 30-day / 365-day display approximations.
# source: calendar arithmetic (SI second; 30-day month / 365-day year display
#   convention).
````
