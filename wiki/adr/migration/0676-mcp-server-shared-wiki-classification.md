---
title: "ADR-0676 — mcp_server/shared/wiki_classification.py rationale"
status: accepted
source: mcp_server/shared/wiki_classification.py
---

# ADR-0676 — mcp_server/shared/wiki_classification.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Implements the schema from ADR-2244 (richer wiki classification).
````

## module — original line 5 (docstring)

````text
**Open-world by design.** Per user direction 2026-05-12, the set of valid
values on each axis is *not* a hardcoded Python frozenset — it is loaded
from the registry in ``mcp_server.core.wiki_axis_registry``, which merges
Python defaults with user-editable files under ``wiki/_schema/<axis>/``.
Adding a new audience or lifecycle value is a wiki edit, not a code edit.
````

## module — original line 11 (docstring)

````text
Validation policy: **reject + suggest**. An unknown value raises
``ValueError`` whose message proposes the closest registered name via
``difflib.get_close_matches`` (user direction 2026-05-12).
````

## module — original line 15 (docstring)

````text
References:
    - ADR-2244 in the methodology wiki
    - docs/research/wiki-classification-survey.md (literature survey)

````

## Classification — original line 69 (docstring)

````text
4-tuple page classification per ADR-2244.
````

## Classification — original line 75 (docstring)

````text
    Fields:
        kind: registered value on the ``kind`` axis (drives directory).
        lifecycle: registered value on the ``lifecycle`` axis;
            ADR-specific lifecycle values (proposed/accepted/rejected/
            superseded) carry ``applies_to_kinds=("adr",)`` in their
            registration so non-ADRs reject them and ADRs reject the
            universal lifecycle.
        audience: tuple of registered values on the ``audience`` axis.
            Multi-valued; must be non-empty.
        provenance: registered value on the ``provenance`` axis.
        generator: required when the provenance value's
            ``requires_generator`` flag is True.
        tags: free controlled-vocabulary tags.
    
````

## validate_classification — original line 109 (docstring)

````text
    A free function, not a method: mutmut categorically excludes the body
    of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:
    236`), so logic placed on `Classification` methods would carry zero
    mutation coverage no matter how the test loader names the module
    (issue #262 3rd pass; issue #282). Split per-axis (§4.2, 40-line cap)
    into `_validate_kind` / `_validate_lifecycle` / `_validate_audience` /
    `_validate_provenance` below — the pre-extraction `validate()` method
    was already 64 lines as a single block; this keeps the orchestrator
    short instead of just relocating the same oversized function.
    
````

## normalize_legacy_kind — original line 245 (docstring)

````text
Map a legacy kind name to its modern equivalent. Returns input unchanged
    when already modern (registered) or unknown.
````

## is_legacy_kind — original line 251 (docstring)

````text
True if the kind belongs to the pre-ADR-2244 taxonomy.
````

## all_known_kinds — original line 256 (docstring)

````text
Modern (registered) + legacy kinds. For read paths that must accept either.
````

## module — original line 26 (comment)

````text
# ── Legacy kind back-compat (read-time only) ────────────────────────────
````

## module — original line 29 (comment)

````text
# Legacy kinds — readable for backward-compat but never produced by new
# writes. The registry does not list these; ``normalize_legacy_kind``
# remaps them on read.
````

## module — original line 43 (comment)

````text
# The wiki has a few pages under ``adrs/`` (plural) — observed during the
# 2026-05-13 Phase 2 pilot. Treated as the same legacy kind as ``adr``.
````

## module — original line 98 (comment)

````text
# __post_init__ is a dunder — mutmut skips the WHOLE decorated
# ClassDef body regardless (`mutmut/mutation/file_mutation.py:236`),
# so this call site carries no mutation coverage either way; kept
# as a method (constructors need one) and calls the free function
# below for the actual validation logic (issue #282).
````

## module — original line 119 (comment)

````text
# Local import avoids importing the registry at module-load time
# (the registry reads the wiki on first call).
````

## inline — original line 121 (directive-rationale)

````text
# noqa: PLC0415 — documented deferral: the registry reads the wiki on first call; a module-load import would also invert the shared->core layer rule at import time
````

## inline — original line 134 (directive-rationale)

````text
# noqa: PLC0415 — see validate_classification
````

## inline — original line 146 (directive-rationale)

````text
# noqa: PLC0415 — see validate_classification
````

## inline — original line 175 (directive-rationale)

````text
# noqa: PLC0415 — see validate_classification
````

## inline — original line 190 (directive-rationale)

````text
# noqa: PLC0415 — see validate_classification
````

## module — original line 241 (comment)

````text
# ── Legacy helpers ──────────────────────────────────────────────────────
````

## inline — original line 257 (directive-rationale)

````text
# noqa: PLC0415 — documented deferral: the registry reads the wiki on first call; a module-load import would also invert the shared->core layer rule at import time
````
