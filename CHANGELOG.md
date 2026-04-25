# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Public-readiness baseline: CONTRIBUTING.md, CODE_OF_CONDUCT.md,
  SECURITY.md.
- GitHub issue templates (bug / feature / audit-finding) and PR template
  with audit-cycle checklist.
- LICENSE expanded with ecosystem-context preamble + explicit
  independent-authorship statement (no employer affiliation).
- `prd-spec-generator` cross-link in companion-projects section.

### Fixed

- `.mcp.json` + `plugin.json` hooks resilient to project-scoped launch.

## [3.14.7] — silent automatised-pipeline installer + ingest_codebase fixes

### Added

- Silent automatised-pipeline self-heal: stale graph slots + multi-roster
  resolver — install/setup-project never errors.
- Canonical domain IDs.

### Removed

- Every `uvx` invocation. Marketplace is the only install path. (See
  ADR-0050.)
- `publish-pypi` from the release workflow. Marketplace only.

### Documentation

- ADR-0050: marketplace is the only path, no uvx ever.
- ADR-0049: Cortex stays local on main; server-side deferred.

## [3.14.0–3.14.6]

### Added

- **v3.14.2** — call graph lit + queryable. Workflow graph renders actual
  call and import edges between symbols. Every edge carries a *confidence*
  (0.0–1.0) and a *reason* tag. Knowledge-graph entities ship as a
  first-class layer (~10k entities). New `query_workflow_graph` MCP tool
  returns typed subgraphs on demand.
- **v3.14.0** — neural graph + AST integration. Workflow graph reveals
  itself one layer at a time: projects → tools → files → code symbols
  (functions / methods / classes) parsed from 10 languages (Rust, Python,
  TypeScript, Java, Kotlin, Swift, Objective-C, C, C++, Go) via the
  automatised-pipeline Rust AST backend.

## [3.x.x] — Earlier 3.x releases

The 3.x series introduced Structured Context Assembly, the BEAM-10M
benchmark integration (+33.4% over the published baseline), the
LongMemEval / LoCoMo benchmark wiring, the predictive-coding write gate,
retrieval-induced reconsolidation, pattern separation (dentate gyrus
model), and sleep-cycle consolidation.

Twenty biological mechanisms across the cognitive-science literature
(41 cited papers); 47 MCP tools; 9 automatic hooks; runs entirely on the
user's machine (PostgreSQL + pgvector, 22MB embedding model).

For per-version detail, see GitHub Releases (v3.0.0 onward) and git
history. This CHANGELOG was seeded at v3.14.7; earlier release notes
remain on the GitHub Releases page.
