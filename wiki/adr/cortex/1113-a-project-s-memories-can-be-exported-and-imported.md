---
created: 2026-10-21T02:42:28Z
kind: adr
number: 1113
status: accepted
tags: [privacy, gdpr, portability, export, import]
title: A project's memories can be exported and imported
---
# ADR-1113: A project's memories can be exported and imported

## Status

accepted

## Context

The three-pillar audit of 2026-10-21 (A8) found no way to export a project's memories: `grep -rliE 'def .*export' mcp_server/handlers` returned nothing on `main` (rerun on `df3a4479` on 2026-10-21: 0 files); the only import paths read foreign systems (claude-mem, ChatGPT, Gemini, transcripts). GDPR article 20 gives a data subject the right to receive the personal data they provided "in a structured, commonly used and machine-readable format" and to transmit it to another controller; for a local tool that means a documented file the user can read, keep, move to another machine or another project, and load back.

Scope questions settled here:

- Which memories belong to a project: `shared/project_scope.py` (ADR-1080) injects memories whose directory is the session root or an ancestor of it, which merges a parent project into its children. An export must not hand one project's file the memories of its parent or of a sibling, so it takes the root and the directories below it, never above.
- What to export: the memories as the user gave them (text, tags, domain, directory, origin, timestamps, flags), not Cortex's computed state (heat, decay, stability, consolidation stage, embeddings), which is not data the user provided and is recomputed.
- Secrets: rows written before ADR-1110 may hold a secret in clear; the export must not carry it out.

## Decision

1. `handlers/memory_portability.py` with a command line `python -m mcp_server.portability`:
   - `export <project-root> <file> [--include-global]`: the current version (supersession chain head) of every memory whose `directory_context` is the root or below it (`= root OR LIKE root/%`, wildcards escaped; the root is made absolute and slash-normalised, symlinks kept, as `project_scope` keeps them), global memories only with the flag, oldest first.
   - `import <file> [--into <project-root>]`: validates the file, moves directories under the exported root to the new root when asked, computes each embedding, inserts through the store, and skips a memory already present with the same content and directory, so a second import adds nothing.
2. Format: JSON Lines, UTF-8. Line 1 is the header `{"format": "cortex-memory-export", "version": 1, "exported_at", "project_root", "include_global", "count", "fields"}`; each following line is one memory with exactly the `fields` keys: `content, tags, domain, directory_context, source, created_at, importance, emotional_valence, is_global, is_protected, is_team_decision, store_type, agent_context, write_class, capture_origin, source_attribution, confidence`. Import refuses a file whose format, version, count or field set do not match.
3. Every exported value passes the redaction gate (ADR-1110) and the file is written `0600` (ADR-1112), wherever the user puts it. Import writes through the gated store, so redaction applies again.
4. The store is the configured one, resolved as the MCP server resolves it.

## Consequences

Evidence (2026-10-21, `tests_py/handlers/test_memory_portability.py`, SQLite temporary file and PostgreSQL 17.9 private cluster, 12 tests): the export holds the project and its subdirectories and not a sibling (`app-other`) or the parent; global memories only on request; the file is `0600` with the documented header; a secret written by an ungated connection (standing in for a pre-ADR-1110 row) leaves redacted; a round trip into another project reproduces the same contents with relocated directories and a second import adds nothing; a malformed or truncated file is refused; the command line exports, imports and refuses a missing file with exit code 1. The module does not exist on `main`.

Limits and next steps:

- Exposed as a command line, not as an MCP tool: a tool needs the registry, `docs/mcp-tools.md`, the tool-count tests and profile decisions; planned.
- Derived structures (entities, relationships, wiki pages, archives) are not exported; the wiki is already plain Markdown on disk. Superseded versions are not exported.
- Retention (automatic purge after a configurable age, audit Track 3.5) is not part of this decision.


## Addendum (2026-10-21): review of PR #775 (B2, N7)

- **An import file is input from outside (B2).** `import_export` trusted it: a record outside the header's root was imported where it said, `..` was not normalised, and `is_global`, `is_protected`, `is_team_decision` were taken as written; a crafted file planted rows in another project and a global protected memory. `handlers/memory_import_checks.py` now validates the whole file before the first insert and fails it on the first violation: header (canonical absolute `project_root`, boolean `include_global`, `fields` equal to this version's), field types (non-empty string content, list of string tags, string or null text fields, finite numbers, booleans, ISO 8601 `created_at`), every directory canonical (no `.`, `..` or empty segment) and equal to or below the root; only a global record of an `include_global` export may come from elsewhere, and it lands at the target root. The sharing flags are off unless the caller passes `trust_flags` (`--trust-flags`).
- **Exact prefix (N7).** The export scope was `directory_context LIKE 'root/%'`; SQLite's `LIKE` folds ASCII case, so a sibling differing by case only was exported. The scope is now `directory_context = root OR substr(directory_context, 1, len(root/)) = 'root/'` on both backends.
