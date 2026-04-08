---
name: cortex-wiki-author
description: "Author first-class wiki pages (ADRs, specs, file docs, notes) that live alongside Cortex memory. Use when the user says 'this is an ADR', 'document this decision', 'write an ADR', 'add a spec', 'spec this out', 'document this file', 'add a note about', 'link these pages', 'bookmark this as a spec', or when finalizing a design decision that should persist as a human-readable document."
---

# Wiki Author — Long-form Documentation Layer

## Keywords
adr, spec, decision, design doc, rfc, file doc, notes, wiki, documentation, link pages, bidirectional link, supersedes, implements, depends on

## Overview

Cortex's wiki is a Markdown authoring surface for the long-form artifacts that don't fit the thermodynamic memory model: architecture decision records, specs, per-file documentation, and free-form notes. Pages live under `~/.claude/methodology/wiki/` and are **never pruned** — they are first-class authored content, not derived views. Every write also registers a protected pointer memory in PostgreSQL so `recall` surfaces wiki pages alongside regular memories.

**Use this skill when:** the user is making a decision that should persist, finalizing a spec, documenting a file's purpose, or asking for two wiki pages to be linked.

**Do NOT use for:** ephemeral facts (use `remember`), domain profiles (use `query_methodology`), or regenerating documentation from memory (the wiki is authored, not projected).

## Workflow

### Record an architecture decision

```
cortex:wiki_adr({
  "title": "Use pgvector for retrieval",
  "context": "We need a searchable memory store with hybrid ranking.",
  "decision": "Adopt PostgreSQL + pgvector + pg_trgm as the single backend.",
  "consequences": "No SQLite fallback. Operator must provision Postgres 15+.",
  "status": "accepted",
  "tags": ["storage", "retrieval"]
})
```

Returns `{ path, number, title, status, ... }`. ADR numbers auto-increment.

### Write a spec

```
cortex:wiki_write({
  "path": "specs/wiki-authoring.md",
  "content": "# Wiki authoring\n\n## Summary\n\nClaude authors ADRs and specs during sessions..."
})
```

Pass the final markdown you want to land. Use `"mode": "append"` to add to an existing page, `"replace"` to overwrite.

### Document a file

```
cortex:wiki_write({
  "path": "files/mcp_server-handlers-wiki_write.md",
  "content": "# `mcp_server/handlers/wiki_write.py`\n\n## Purpose\n\nComposition root for the wiki authoring tool..."
})
```

### Link two pages bidirectionally

```
cortex:wiki_link({
  "from_path": "adr/0001-use-pgvector-for-retrieval.md",
  "to_path": "specs/retrieval-pipeline.md",
  "relation": "implements"
})
```

Adds the forward relation to `from_path` and the inverse (`implemented_by`) to `to_path`. Idempotent. Known relations: `supersedes`/`superseded_by`, `implements`/`implemented_by`, `depends_on`/`depended_on_by`, `derived_from`/`derives`, `see_also`.

### Read a page (to update it)

```
cortex:wiki_read({ "path": "adr/0001-use-pgvector-for-retrieval.md" })
```

### List pages

```
cortex:wiki_list({})                   // all kinds
cortex:wiki_list({ "kind": "adr" })    // just ADRs
```

### Regenerate the table of contents

```
cortex:wiki_reindex({})
```

Writes `.generated/INDEX.md`. This is the only file ever auto-regenerated — authored pages are untouched.

## Layout

```
~/.claude/methodology/wiki/
  adr/NNNN-<slug>.md       # numbered decision records
  specs/<slug>.md          # feature specs, PRDs, design docs
  files/<slug>.md          # per-source-file documentation
  notes/<slug>.md          # free-form notes and investigations
  .generated/INDEX.md      # auto-generated table of contents
```

## Tips

- **No prune, ever.** Authored pages survive across sessions, version bumps, and machine moves (as long as the wiki root is preserved).
- **ADR numbers are monotonic.** Don't reuse them — supersede instead via `wiki_link(new, old, "supersedes")`.
- **Links live in the page.** The `## Related` section is the source of truth for wiki-internal links — not a sidecar index.
- **Wiki pages are recallable.** After `wiki_write`, the page content (first 500 chars) is indexed in PostgreSQL as a protected memory tagged `wiki`, so `recall` returns it alongside regular memories.
- **Back-links are authoritative.** `wiki_link` always updates both pages. If you move or rename a file, re-run `wiki_link` so the related sections stay consistent.
