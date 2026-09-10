---
kind: adr
number: 0503
title: Preserve artifact_gc design decisions
status: accepted
---

# ADR-0503: artifact_gc design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/artifact_gc.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
`artifact_store` writes content-addressed artifacts and never removes them.
That is safe while nothing deletes memories, but `forget` claims — in
PRIVACY.md, to users — that it deletes a memory. A gist+pointer memory keeps
its FULL raw text in the artifact, so deleting only the row leaves the content
readable on disk (issue #366).
````

### count_artifact_references, original line 36

````text
    Pre: ``conn`` is a live store connection (PgMemoryStore's psycopg
    connection or the SQLite `PsycopgCompatConnection`, which translates the
    ``%s`` placeholder); ``artifact_path`` is a non-empty path string.
    Post: returns the count of rows in ``memories`` whose ``content`` contains
    the path. Substring match is the correct test here because the pointer line
    embeds the path verbatim and is the only place a memory body carries it.
````

### count_artifact_references, original line 36

````text
    Raises whatever the driver raises — a failure to COUNT must NOT be read as
    "zero references", which would delete a still-referenced artifact. The
    caller decides how to degrade; see ``delete_artifact_if_unreferenced``.
    
````

### delete_artifact_if_unreferenced, original line 66

````text
    Pre: the referring memory row has ALREADY been deleted — otherwise it
    counts itself and the artifact is never collected. ``artifact_path`` may be
    None (memory had no artifact), in which case this is a no-op.
    Post: returns True only when the file was actually unlinked. Returns False
    when there was no artifact, when another memory still refers to it, when
    the file is already gone, or when the reference count could not be
    established. Never raises: a failure to collect an artifact must not fail
    the deletion of the memory the user asked to forget, and every non-removal
    path logs why.
    
````

### comment, original line 84

````text
# Fail CLOSED: an unknown reference count must not authorize a delete.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### module: final review

````text
Reference-counted removal of raw-output artifacts.

Removal cannot be unconditional. `store_artifact` is content-addressed with
dedup: two captures of byte-identical output map to ONE file. Deleting that
file when the first of two referring memories is forgotten would leave the
second memory's pointer dangling at a path that no longer exists. So this
module answers "is anyone still referring to this artifact?" before unlinking.

Separate module from `artifact_store` on purpose: that one owns filesystem
writes and has no database dependency. Garbage collection needs both the store
and the filesystem, and mixing them into the writer would give it two reasons
to change (SRP).

source: ADR-0503
````

### count_artifact_references: final review

````text
Number of memories whose body still points at ``artifact_path``.

    Uses ``COUNT(*) AS c`` + ``row["c"]`` with ``row_factory=DICT_ROW``, the
    shared cross-backend scalar convention (cf. count_relationships /
    count_entities): the SQLite compat cursor yields mapping rows, so reading
    by position raises KeyError there.

Raises whatever the driver raises — a failure to COUNT must NOT be read as
    "zero references", which would delete a still-referenced artifact. The
    caller decides how to degrade; see ``delete_artifact_if_unreferenced``.

source: ADR-0503
````
