---
kind: adr
number: 0522
title: Preserve embedding_fallback_provider design decisions
status: accepted
---

# ADR-0522: embedding_fallback_provider design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/embedding_fallback_provider.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Download-free algorithmic embedding provider (issue #169).
````

### module, original line 1

````text
The SECOND ``EmbeddingProvider`` implementation (the first is the neural
``EmbeddingEngine``). It produces deterministic vectors with no model download,
no network, and no learned parameters — only arithmetic seeded by the token
strings — in the SAME dimension contract as the neural encoder. Used whenever
the neural model is not loadable (``ModelState`` PACKAGE_ABSENT /
MODEL_FILES_ABSENT / LOAD_RAISED); the factory maps those states here.
````

### module, original line 1

````text
The vectors live in a DIFFERENT geometry from the neural space, so the store
tags each stored vector with the producing provider and never cross-ranks the
two (see ``sqlite_store``). Pure delegation to
``shared.algorithmic_embedding`` — see that module for the signal selection
(TF + Random Indexing + co-occurrence bridging) and its sources.

````

### AlgorithmicEmbeddingProvider, original line 26

````text
    Stateless apart from its fixed dimension; safe to share across threads
    (``embed_text`` allocates its own arrays). Inherits the shared vector math
    (``similarity`` / ``to_list`` / ``from_list`` / ``_normalize`` / ``_cache_key``)
    so it satisfies the provider surface identically to the neural engine.
    
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
