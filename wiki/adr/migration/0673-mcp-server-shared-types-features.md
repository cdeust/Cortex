---
title: "ADR-0673 — mcp_server/shared/types_features.py rationale"
status: accepted
source: mcp_server/shared/types_features.py
---

# ADR-0673 — mcp_server/shared/types_features.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Types the internal core-layer boundary between mcp_server/core/{persona_vector,
attribution_tracer, behavioral_crosscoder, sparse_dictionary}.py and their
consumers (mcp_server/handlers/explore_features.py,
mcp_server/core/profile_assembler.py). Prior to this module those functions
returned dict[str, Any] — a §3.2 coding-standards violation (untyped dict
across a layer boundary).
````

## module — original line 10 (docstring)

````text
Field names mirror the JSON keys these modules already produce (camelCase,
matching the JS-era MCP/profiles.json contract). This is a typing-only
refactor: it does not change what is computed, only what carries the result.
````

## module — original line 14 (docstring)

````text
Two data-provenance families, two ``extra`` policies:
  - FeatureDictionary / Feature / TopSignal / PersistentFeature round-trip
    through profiles.json (written by profile_assembler.py, re-read by
    explore_features.py via load_profiles()). They use extra="ignore" —
    the same tolerance types_profiles.py uses for JS-authored data.
  - EncodedSession / PersonaDrift / AttributionNode / AttributionEdge /
    AttributionGraph are computed fresh in-process every call and never
    persisted. They use extra="forbid" — the stricter policy wiki_ir.py
    uses for pure-internal pipeline types.
````

## module — original line 24 (docstring)

````text
Feature.direction is Optional: the live sparse_dictionary.py output always
includes it, but profile_assembler._build_feature_dictionary() strips it
before persisting to profiles.json (disk-loaded features never carry it).
This models the real observed union of shapes, not an approximation.

````

## AttributionNode — original line 91 (docstring)

````text
    activation is always numeric. 3 of the 6 classifier nodes
    (problemDecomposition, explorationStyle, verificationBehavior) classify
    a *categorical* CognitiveStyle value (see types_profiles.CognitiveStyle,
    e.g. "top-down"/"bottom-up") that has no legitimate scalar magnitude --
    fabricating a number for it would be a silent, unsourced cast. Those
    three nodes carry activation=0.0 (no measured magnitude) and expose the
    classification separately via categoricalValue. The other three
    classifier nodes and all non-classifier nodes leave categoricalValue
    unset and carry a real float in activation.
    
````
