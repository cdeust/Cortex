---
kind: adr
number: 0521
title: Preserve embedding_factory design decisions
status: accepted
---

# ADR-0521: embedding_factory design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/embedding_factory.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Composition root for the embedding subsystem (Cortex#173, seam 3).
````

### module, original line 1

````text
This is the "engine selection / wiring" seam: the single place that reads the
runtime settings (``EMBEDDING_DIM`` / ``EMBEDDING_DEVICE``) and assembles the
process-wide encoder. Consumers call ``get_embedding_engine()`` rather than
constructing an ``EmbeddingEngine`` themselves, which guarantees one model, one
device, no mixed-device embeddings, ~5x memory savings.
````

### module, original line 1

````text
Keeping selection here — separate from the concrete providers
(``embedding_engine.EmbeddingEngine``, neural, and
``embedding_fallback_provider.AlgorithmicEmbeddingProvider``, download-free) and
their interface (``embedding_provider.EmbeddingProvider``) — is what lets the
active provider be chosen per ``ModelState`` (``use_fallback``) with no consumer
change (issue #169).
````

### module, original line 1

````text
Import-cycle note: the concrete ``EmbeddingEngine`` (and ``get_memory_settings``)
are imported lazily *inside* ``get_embedding_engine`` so this module has no
module-load dependency on ``embedding_engine`` — ``embedding_engine`` re-exports
these functions, so the two modules must not import each other at top level.
``ModelState`` comes from ``embedding_model_lifecycle`` (no cycle).

````

### use_fallback, original line 51

````text
Whether ``state`` selects the algorithmic fallback provider (issue #169).
````

### current_embedding_mode, original line 60

````text
Return the process-wide embedding provenance for telemetry (issue #169).
````

### comment, original line 36

````text
# The state→provider selection (issue #169). Every ModelState that is not a
# loaded neural model routes to the download-free algorithmic fallback —
# PACKAGE_ABSENT, MODEL_FILES_ABSENT (download pending), LOAD_RAISED, and the
# not-yet-attempted UNINITIALIZED. NO state maps to nothing.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
