# ADR-0398: mcp_server/handlers/import_sessions.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/import_sessions.py`; original SHA-256 `24ca9910d1eace30d13f8f8f767182125e854da3af88245bfc775d388ed00691`.

## Original docstring, lines 1–23

````text
"""Handler: import_sessions — import conversation history into memory store.

Scans JSONL conversation files from ~/.claude/projects/ and extracts
memorable content (decisions, errors, architecture notes, insights).
Stores via the remember handler's full pipeline (thermodynamics, write gate,
knowledge graph, engram allocation).

Supports:
  - Full import: all projects
  - Project filter: specific project directory
  - Domain filter: specific domain
  - Dry run: preview what would be imported without storing

latency_class: long_running

Memory discipline: this handler ONLY reads JSONL files via the streaming
head+tail path (``read_head_tail`` in scanner.py). No whole-file accumulator
list exists. See ADR-0045 R2 ("no ingestion path reads a whole file/store
into Python memory"); the former ``full_read=True`` branch was removed in
v3.13.0 Phase 1 because it materialised entire multi-GB JSONLs in a Python
list before extraction, producing an OOM path that Taleb's audit flagged as
a black-swan failure mode on large histories.
"""
````

## Original docstring, lines 142–152

````text
"""Read JSONL records via streaming head+tail only.

    precondition: ``file_path`` points to a (possibly multi-GB) JSONL file.
    postcondition: returns a bounded list of parsed dict records whose total
    on-disk span is ≤ HEAD_BYTES + TAIL_BYTES (~40 KB) regardless of file
    size; the function never materialises the whole file in memory.

    Source: ADR-0045 R2 — no ingestion path reads a whole file/store into
    Python memory. The previous ``full_read`` branch was deleted in v3.13.0
    Phase 1.
    """
````

## Original comment, lines 186–191

````text
# Preserve the original session timestamp. insert_memory anchors
    # heat_base_set_at to it (A3 decay clock), so effective_heat() decays the
    # baseline by the memory's real age at READ time — the single canonical
    # age-decay path. We deliberately do NOT pre-decay initial_heat here: that
    # would double-count the same age. A3's read-time decay also spreads the
    # import cohort by age, subsuming the original issue #14 bimodality fix.
````

## Original comment, lines 200–202

````text
# Dry-run preview truncation caps.
# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

