---
title: "ADR-0685 — mcp_server/shared/wiki_readme.py rationale"
status: accepted
source: mcp_server/shared/wiki_readme.py
---

# ADR-0685 — mcp_server/shared/wiki_readme.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
The wiki's technical content lives in `<kind>/<domain>/<slug>.md` files
with templated front-matter + section structure — tech-ready, but dense.
This module generates a top-level ``README.md`` that is readable by
non-technical stakeholders:
````

## module — original line 8 (docstring)

````text
  * What the wiki IS (one paragraph, plain language).
  * What lives WHERE (kind-labelled sections with a 1-line "what it's
    for" summary, not "architecture decision record" jargon).
  * How to NAVIGATE (auto-generated table of contents + link to the
    detailed technical INDEX.md).
  * When it was last GROOMED (builds trust: "this is current").
````

## module — original line 15 (docstring)

````text
Design principle: non-tech readers see plain language at the top;
tech readers follow links down to the structured INDEX + per-page
templates. No information is hidden from either audience — just
presented at the right depth for each click.
````

## module — original line 20 (docstring)

````text
Source: user directive "wiki generation, folder and file management,
keep this tidy, in order, readable by non tech while having all
information needed for tech people".

````

## _render_navigation_and_contributors — original line 172 (docstring)

````text
``## Go deeper`` + ``## For contributors`` — static boilerplate,
    no input dependency (unlike the other three sections).
````

## build_plain_readme — original line 212 (docstring)

````text
    The output is stable (same input → same output, modulo the
    ``generated_at`` timestamp) so it's safe to write on every reindex
    without churning the git log. Composed from four section builders:
    ``_render_readme_header``, ``_render_whats_here``, ``_render_domains``,
    ``_render_navigation_and_contributors``.
    
````

## module — original line 95 (comment)

````text
# source: structural — a domain-scoped page path is kind/domain/filename, so
# fewer than three parts carries no domain (root-level page).
````
