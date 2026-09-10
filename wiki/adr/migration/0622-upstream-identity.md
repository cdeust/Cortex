---
kind: adr
number: 0622
title: Preserve upstream_identity design decisions
status: accepted
---

# ADR-0622: upstream_identity design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/upstream_identity.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
The producer was renamed twice — ``automatised-pipeline`` ->
``ai-architect-codebase`` -> ``ai-architect-mcp-codebase`` (canonical since
v0.9.0, 2026-08-04). Cortex resolves that server three different ways (release
asset, marketplace install, PATH lookup) and validates the resolved command
against a security allowlist, so the producer's names were hardcoded in five
modules. When the producer renamed its binary once before, only some of those
copies were updated; the pool allowlist was missed and every ingest failed with
"Command not in allowed list" (CHANGELOG 3.14.11). One copy per module is what
made that recurrence possible, so the names live here and nowhere else.
````

### module, original line 1

````text
The producer publishes ``mcp-contract.json`` as the machine source of truth.
The values below mirror it and are verified against it in CI
(.github/workflows/upstream-identity.yml), pinned to a commit SHA rather than a
tag because the producer's README is explicit that tags can be moved:
https://raw.githubusercontent.com/cdeust/ai-architect-mcp-codebase/37728cc5747cebe39ea9d4011b7424de90f0a57b/mcp-contract.json
````

### module, original line 1

````text
Legacy names are kept as *fallbacks*, never as the primary: installs predating
v0.9.0 still carry the old marketplace key on disk, and the producer still
ships an ``automatised-pipeline`` ``[[bin]]`` alias. That alias is explicitly
labelled "Compatibility alias only" upstream, so it is a bridge, not a contract.

````

### built_binary_relatives, original line 66

````text
    source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.5 — Windows builds emit
    an .exe; the extension-less name is the Linux/macOS artifact.
    
````

### comment, original line 29

````text
# --- canonical (mcp-contract.json) -----------------------------------------
````

### comment, original line 36

````text
# --- legacy, resolvable but never preferred --------------------------------
# Ordered oldest-last so the canonical name always wins a lookup.
````

### comment, original line 42

````text
# Each plugin key's install ships its binary under target/release/<name>; the
# key and the binary renamed together, so they are paired rather than crossed.
````

### comment, original line 50

````text
# Commands the upstream bridge may spawn. mcp_client validates a resolved
# command against this set by basename; omitting the canonical name here turns
# a correct resolution into "Command not in allowed list", which is exactly how
# the 3.14.11 regression presented.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
