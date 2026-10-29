---
title: Canonical wiki decisions with reviewable generated mirrors
kind: decision
status: accepted
decision_id: ADR-0056
---

# ADR-0056 — Canonical wiki decisions with reviewable generated mirrors

## Context

Issue [#514](https://github.com/cdeust/Cortex/issues/514) measured competing
identifier schemes and failed lexical retrieval of hyphenated IDs. The owner
selected option C on 2026-09-09: retain the wiki as the authored source while
keeping decision text reviewable in pull requests.

## Decision

Project-authored decisions live in the versioned `wiki/adr/` tree. The explicit
`wiki/manifest.json` maps each canonical ADR-NNNN ID to its source and generated
`docs/adr/` filename. Existing mirror filenames and historical numbers remain
stable. IDs 0001–0055 are reserved; 0014–0043 are reserved gaps whose cause is
unknown. IDs are unique across domains within one wiki root. Duplicate IDs,
malformed manifests and stale indexes fail explicitly.

`wiki_reindex(project_root=...)` publishes a deterministic read-only mirror.
CI compares complete mirror bytes against tracked canonical pages and rejects
missing, changed or unexpected mirrors. It requires no operator wiki, database
or network. Project selection is explicit; private global wiki pages are never
selected for publication by inferred domain or by scanning the global wiki.

Bare ADR-NNNN queries and explicit exact-ID mode resolve the index before
embedding, memory or code search. Missing IDs are reported without a semantic
fallback. Ordinary memory retrieval keeps its existing behavior. Explicit
project unified search also includes a lexical wiki lane.

Project authoring changes tracked files and generated artifacts only; it does
not publish unmerged branch text into global pointer memories or PostgreSQL
wiki metadata. Global wiki authoring retains its existing pointer behavior,
with the canonical ID added to pointer content. New source annotations use
`# source: ADR-NNNN`; craftsmanship resolves those IDs to canonical pages.

The repository migration archives decision rationale, citations and historical
references from source and build configuration, preserving the original excerpts
and source digests. Code retains canonical decision pointers and operational
contracts. Python executable ASTs are compared with docstrings excluded;
intentional tool-description changes are checked separately. SQL and shell
changes require token or executable-content equivalence. Generated mirrors
expose the archived rationale in the same pull request as each extraction.
Malformed numeric global wiki page names can be quarantined by an explicit,
byte-preserving migration.

## Consequences and verification

The wiki is the editing interface; the generated mirror adds review-visible
text, not a second authoring authority. Project-root selection scopes IDs;
callers must supply the same project when resolving its decisions. Runtime
index metadata is regenerated on each checkout and is not portable Git data.

Tests cover duplicate IDs, stale maps, reserved allocation, mirror drift,
path escapes, exact lookup without model calls, and migration rollback.
The known-item benchmark reports recall@1 and MRR@10 with explicit baseline
conditions. [Retiré 2026-10-29 : porte de non-régression contre main supprimée sur ordre de l'owner ; les benchmarks sont une mesure, pas une porte.]

## Preserved governed wiki-write contract

## Wiki write governance contract

The governed wiki-write path — adds pointer-memory + citation
bookkeeping on top of a plain ``write_page`` call.

precondition: ``root`` is a wiki root (production ``WIKI_ROOT`` or, for a
caller operating on an alternate tree such as a test fixture, that
tree's own root); ``rel_path`` is root-relative; ``content`` is the full
markdown (frontmatter + body) to persist.
postcondition: write-time frontmatter normalization (issue #107) is
enforced by ``write_page`` itself (issue #110 — the choke point moved
down to ``infrastructure.wiki_store`` so it covers every caller, not
just this one), so this function no longer needs to (and does not)
call ``normalize_frontmatter`` a second time. On success, the page is
written atomically (tmp+rename, ``write_page``'s existing guarantee)
AND a protected ``write_class='mechanical'`` pointer memory is stored
via ``remember`` (best-effort — never blocks or fails the write;
mechanical is correct per remember_schema.py's own vocabulary:
"structural indexing — ... wiki pointer sync — bypasses the gate
entirely, force=true semantics"; this call stores a 500-char pointer,
not the full authored content, so the class describes the
pointer-write, not who authored the page body) AND
``wiki.pages``/``wiki.citations`` are synced best-effort (same
degrade-to-no-op discipline as ``_sync_page_and_cite``'s own contract).
Write-time provenance grading (``INC7.5`` — ``grade_from_content``,
triggered inside ``remember()``'s insert path) fires automatically as a
consequence of routing through here; no separate grading call is needed.
Returns ``{path, mode, created, bytes_written, root, citations_written}``
or ``{error}``.

This is the ONLY function in the codebase that may register the
pointer-memory + citations governance side effects — the interactive
``wiki_write`` MCP tool (``handler``, below) and the headless
authoring worker (``consolidation/page_io.py``) both route through
here so no caller performing an authored, citable write skips that
bookkeeping. It is emphatically NOT the only caller of ``write_page``:
several handlers (redirect stubs, generated reference/PRD/finding
pages, ADRs, links) call ``write_page`` directly because pointer
memories and citations do not apply to their output — see
``tests_py/architecture/test_write_page_call_sites.py`` for the
audited whitelist that guards against a new, unreviewed direct
caller appearing silently. Frontmatter normalization is unconditional
for all of them regardless (see ``write_page``'s own contract).

raises: ``UnclosedFrontmatterError`` (propagated, uncaught, from
``write_page``'s call to ``normalize_frontmatter``) when ``content``
opens a frontmatter fence it never closes — the one shape that is
structurally inexploitable. The interactive tool call (``handler``,
below, registered via ``safe_handler``) turns this into a
``mcp.server.mcpserver.exceptions.ToolError`` automatically (the repo's standing
idiom — see commits c7dfc243/49f29e98); ``consolidation/page_io.py``'s
non-tool callers catch it explicitly and degrade to their existing
failure contract.

## Publication file safety

Private temporary-directory regression cases demonstrated that predictable
`page.md.tmp` and generated `INDEX.md.tmp` symlinks could cause the prior
writer to overwrite a file outside the wiki. The writer now creates an
exclusive unpredictable temporary file before replacement. Project snapshot
and rollback paths are checked for containment, and project operations validate
the original absolute-root argument before normalization. Tests retain outside
sentinels to verify these cases. Individual file replacements are atomic;
project publication does not promise a multi-file snapshot to concurrent readers.
