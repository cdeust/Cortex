---
kind: adr
number: 0523
title: Preserve embedding_model_lifecycle design decisions
status: accepted
---

# ADR-0523: embedding_model_lifecycle design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/embedding_model_lifecycle.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of ``embedding_engine.py`` (Cortex#173) so the download/cache/load
lifecycle is an explicit, testable seam rather than an inline tangle. The
``ModelState`` enum names the distinct outcomes the loader can reach — the
state space where a silent-degradation bug can hide:
````

### module, original line 1

````text
Model revision pin (reproducibility gap closed 2026-07-11, incident i7d3):
  ``huggingface_hub`` resolves an unpinned model name against the repo's
  moving ``refs/main`` pointer. Root-cause investigation of a benchmark
  regression found TWO snapshots cached locally for
  ``sentence-transformers/all-MiniLM-L6-v2`` (``c9745ed1...`` from
  2026-04-04 and ``1110a243...`` from 2026-06-09) — ``refs/main`` had moved
  between them. In that specific incident the underlying
  ``model.safetensors``/``config.json``/``tokenizer.json`` blobs were
  confirmed BYTE-IDENTICAL across both snapshots (same SHA256 content
  hash) by direct cache inspection, so it was not the cause of THAT
  regression — but the gap itself is real and unbounded: nothing stops a
  future upstream repo change (a genuine weight update, not just a
  metadata/README commit) from silently altering embeddings for every
  caller that resolves ``main`` at load time, with no signal in
  ``uv.lock`` (which pins the Python package, not the HF model weights).
  ``DEFAULT_MODEL_REVISION`` below pins the exact snapshot verified during
  that investigation; ``EmbeddingEngine`` uses it whenever the caller does
  not supply an explicit ``revision``. source: measured on 2026-07-11 via
  ``~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/refs/main``
  and blob-hash comparison of the two cached snapshots.

````

### ModelState, original line 68

````text
Explicit lifecycle states of the neural model load (Cortex#173).
````

### embedding_cache_dir, original line 78

````text
    Mirrors ``mcp_server.core.reranker.reranker_cache_dir`` (hardened
    after the FlashRank /tmp incident, commit bb1c581f): same shared,
    XDG-aware ``mcp_server.shared.platform.cache_dir()`` base, laid out
    under ``huggingface/hub`` to match the directory
    ``sentence-transformers``/``huggingface_hub`` already write
    ``models--org--name`` snapshots into by default (``$HF_HOME/hub``).
````

### embedding_cache_dir, original line 78

````text
    Precedence, decided for consistency with how ``huggingface_hub``
    itself resolves its cache (``cache_folder`` passed to
    ``SentenceTransformer`` takes priority over both env vars inside the
    library, so passing one unconditionally would silently override a
    choice the user already made): if ``HF_HOME`` or
    ``SENTENCE_TRANSFORMERS_HOME`` is set in the environment, return
    ``None`` and let the library resolve its own default from that env
    var. Otherwise return our durable, shared cache path so a caller who
    set neither var still gets a deterministic, XDG-aware location
    instead of depending entirely on ``huggingface_hub``'s built-in
    resolution (issue #124 — the reranker was hardened this way in
    bb1c581f; embeddings had no equivalent).
    
````

### _EmbeddingLifecycleMixin, original line 106

````text
    A mixin so ``EmbeddingEngine`` keeps exposing ``_detect_device`` /
    ``_resolve_device`` / ``_ensure_model`` on the class (the tests patch and
    call them there). Reads/writes the engine attributes declared below, all
    owned by ``EmbeddingEngine.__init__`` except the guard configured on load.
    
````

### _construct_model, original line 184

````text
Build one ``SentenceTransformer``. Import is at call time so the
        ``sentence_transformers.SentenceTransformer`` patch point still works.
````

### _construct_model, original line 184

````text
        ``local`` toggles ``local_files_only=True`` — hermetic (no HF Hub
        requests) when the model is already cached. It must be an explicit
        kwarg, not HF_HUB_OFFLINE, which hub freezes into module constants at
        first import (reproduced 2026-07-03). source: kwarg added in
        sentence-transformers v3.0.0.
        
````

### _load_model, original line 228

````text
        Never blocks and never crashes the caller (issue #169): a cache miss
        (MODEL_FILES_ABSENT) or an unexpected construction failure (LOAD_RAISED)
        engages the download-free fallback for THIS session and kicks off a
        background fetch so the next session is neural. Only ``ImportError``
        (PACKAGE_ABSENT) escapes, handled by ``_ensure_model``.
        
````

### _engage_fallback, original line 271

````text
        precondition: called from the load path when the neural model cannot be
        served this session.
        postcondition: ``model_state`` is ``state`` and ``_unavailable`` is True;
        exactly one WARNING is logged (issue #169) so the degrade is never
        silent — the factory then routes encode() to the algorithmic provider.
        
````

### comment, original line 58

````text
# source: measured 2026-07-11 (incident i7d3) — see module docstring
# "Model revision pin" section for the full derivation and the blob-hash
# verification that this snapshot's weights are byte-identical to the
# immediately-prior cached snapshot.
````

### comment, original line 198

````text
# explicit, XDG-aware default (mirrors reranker bb1c581f) unless the
            # user already set HF_HOME / SENTENCE_TRANSFORMERS_HOME (issue #124).
````

### comment, original line 208

````text
# sentence-transformers 5.x renamed get_sentence_embedding_dimension →
        # get_embedding_dimension. Prefer the new name; fall back for <5.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
