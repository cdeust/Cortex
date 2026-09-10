---
kind: adr
number: 0520
title: Preserve embedding_engine design decisions
status: accepted
---

# ADR-0520: embedding_engine design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/embedding_engine.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Strategy (selected by the factory per ``ModelState``, issue #169):
  1. sentence-transformers (``ModelState.LOADED``) -- best quality, 384D
  2. Download-free algorithmic fallback (every non-LOADED state) --
     ``embedding_fallback_provider.AlgorithmicEmbeddingProvider``, the SECOND
     ``EmbeddingProvider`` implementation. No state maps to nothing.
````

### module, original line 1

````text
Structure (Cortex#173 — the file was split along three seams):
  * ``embedding_provider.EmbeddingProvider`` — the interface consumers depend
    on; ``EmbeddingEngine`` below is the neural implementation, the algorithmic
    fallback is the second.
  * ``embedding_model_lifecycle`` — device resolution + the explicit model-load
    state machine (``ModelState``: package absent / model files absent / load
    raised / loaded). See that module's docstring for the revision-pin history.
  * ``embedding_factory`` — the composition root: it wires the two providers and
    owns the state→provider selection (``use_fallback``, ``current_embedding_mode``).
  * this module — the concrete neural provider (encode path + LRU cache).
````

### EmbeddingEngine, original line 82

````text
    Cache key discipline (ADR-0045 R5): the LRU cache is keyed by
    ``sha256(text)[:16]`` (16 hex chars = 8 bytes of entropy), never by
    raw text. Each key stores 16 characters regardless of input length.
    Cache key storage scales with the entry count, not the memory text size.
    The capacity is measured in docs/provenance/embedding-cache-capacity.md.
    
````

### model_state, original line 139

````text
The current lifecycle state of the neural model load (Cortex#173).
````

### mode, original line 144

````text
Embedding provenance: ``"neural"`` or ``"fallback"`` (issue #169).
````

### _serve_fallback, original line 157

````text
        After ``_ensure_model``, a loaded neural model has ``self._model`` set
        (state LOADED); every fallback ModelState leaves ``self._model`` None.
        A present model always takes the neural path; otherwise the factory's
        per-ModelState mapping (``use_fallback``) decides — so no state maps to
        nothing (issue #169).
        
````

### encode, original line 206

````text
        The LRU cache is keyed by ``sha256(text)[:16]`` per ADR-0045 R5
        — never by raw text — so a 100 KB memory contributes 16 bytes of
        key storage, not 100 KB.
        
````

### warm_cache, original line 261

````text
        Lets a caller about to make many individual ``encode()`` calls for
        already-known text (e.g. backfill importing a session file's items
        one ``remember()`` at a time -- issue: green-software review
        2026-09-04) pay one batched model inference instead of
        ``len(texts)`` sequential ones: each subsequent ``encode()`` call
        for a warmed text becomes a cache hit. Already-cached and duplicate
        texts are skipped/deduped before encoding.
````

### _fallback_encode, original line 290

````text
Delegate to the algorithmic fallback provider (issue #169).
````

### comment, original line 62

````text
# Re-exported for backward compatibility: callers and tests import these names
# from ``embedding_engine`` directly (they lived here before the Cortex#173
# split). The definitions now live in the seam modules — ``embedding_provider``
# (interface), ``embedding_model_lifecycle`` (revision pin + cache dir), and
# ``embedding_factory`` (composition root / selection + telemetry mode).
````

### comment, original line 106

````text
# revision=None means "resolve refs/main at load time" (the
        # pre-i7d3 unpinned behavior) — an explicit opt-out for callers
        # that pass a different model_name this pin was never verified
        # against. See embedding_model_lifecycle "Model revision pin".
````

### comment, original line 114

````text
# The SECOND provider (issue #169): the download-free algorithmic
        # encoder the factory routes to for every non-LOADED ModelState. Same
        # dimension contract as this neural engine.
````

### comment, original line 118

````text
# Cache keyed by sha256(text)[:16] — see class docstring / ADR-0045 R5.
````

### comment, original line 120

````text
# source: docs/provenance/embedding-cache-capacity.md — eviction counterexample.
````

### comment, original line 192

````text
# Already on CPU — genuine bug, don't mask
````

### comment, original line 224

````text
# Selection per ModelState is owned by the factory (issue #169):
        # LOADED → neural encode; every other state → the algorithmic fallback.
````

### comment, original line 298

````text
# Non-empty text always yields a vector; guard the type only.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
