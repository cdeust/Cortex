---
kind: adr
number: 0633
title: Preserve workflow_graph_ast_symbols design decisions
status: accepted
---

# ADR-0633: workflow_graph_ast_symbols design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/workflow_graph_ast_symbols.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
AST *symbol* loading for the workflow graph (ADR-0046).
````

### module, original line 1

````text
Split out of ``workflow_graph_source_ast.py`` (issue #275 — that file
exceeded the 300-line cap) as its own cohesive concern: querying AP for
symbol nodes (Function/Method/Struct/...) and normalizing them into the
builder-shaped dict the workflow graph consumes.
````

### _where_for_tails, original line 107

````text
    Each tail produces one STARTS WITH predicate on qualified_name (or
    id for Import nodes). We emit the shortest unique tails only — if
    "pkg/mod.py" is present, "mod.py" is redundant because any match for
    "mod.py" also matches "pkg/mod.py". Cap at ``_MAX_WHERE_TAILS`` to
    keep the WHERE clause tractable.
    
````

### symbol_batches_async, original line 206

````text
    AP stores each symbol under its own label (Function, Method, Struct,
    Enum, Trait, Constant, TypeAlias, ...). The qualified_name follows
    ``<relative_file>::<name>``. We query each label separately (LadybugDB
    rejects multi-label ``MATCH``). Each label's rows are yielded as soon
    as its query returns, so the consumer can process/discard a label's
    rows before the next label is queried — peak retained here is one
    label's rows, not the union across all ``_SYMBOL_LABELS`` queries.
````

### comment, original line 21

````text
# AP's node labels carrying symbol semantics. Derived from
# stage-3 tree-sitter extractors; see
# ``ai-architect-mcp-codebase/src/clustering.rs`` for the canonical list.
````

### comment, original line 25

````text
# Core — Rust + Python (original set)
````

### comment, original line 50

````text
# Import statements (one node per ``import`` site). AP wires every
    # file to its imports via the ``Defines_File_Import`` rel table; the
    # nodes themselves carry ``id`` (``<file>::<modpath>``), ``path``,
    # ``alias``, ``is_glob``. Loaded via a custom property mapping below
    # because imports lack ``qualified_name``.
````

### comment, original line 58

````text
# Labels whose nodes don't expose ``qualified_name`` / ``name``. The
# load query falls back to ``id`` / ``path`` (or whatever the node
# DOES carry) so they still flow into the graph.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### Tool directive rationale

````text
# source: "Cap at 10 tails to keep the WHERE clause tractable"  # noqa: ERA001
# (comment in _symbol_batches_async._where_for_tails)  # noqa: ERA001
````
