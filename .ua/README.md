# `.ua/` — Understand-Anything knowledge graph of Cortex

Graph of the repository at commit `df3a447` (main, 2026-10-17), built on 2026-10-20 with
the Understand-Anything plugin 2.9.7 (`/understand`), then completed by the deterministic
passes in `gapfix/`. Every node and edge those passes add comes from the code (AST, SQL
string literals, coverage.py dynamic contexts) or from what the repository already
documents (`docs/mcp-tools.md`, `.claude-plugin/plugin.json`, `wiki/manifest.json`, the
ADR pages, docstrings), and records its evidence (`file:line`).

## Contents

| Path | What it is |
|---|---|
| `knowledge-graph.json.gz` | The graph read by the dashboard (versioned compressed; see *Viewing*): files, functions, classes, configs, docs, store tables; layers; 14-step tour; knowledge layer (ADR articles, topics, scientific sources) |
| `domain-graph.json` | Domain view: 6 domains, 71 flows (one per MCP tool and per hook), their ordered steps |
| `overlays/diff-overlay-<pr>.json` | Impact of PRs #770–#773: changed nodes, affected nodes, entry points, tests |
| `meta.json`, `config.json`, `fingerprints.json`, `.understandignore`, `intermediate/` | Understand-Anything metadata, per-file fingerprints (incremental updates), scan result |
| `reports/` | Diagnostic report, coverage cycles 0–2, dead-code candidates, coverage scorecard, `/understand` phase warnings (moved from `.ua/phase-warnings.txt`: `tests_py/scripts/test_uv_lock_single_source.py` refuses a shallow `.txt`) |
| `probe/` | Probe that measured PostgreSQL dials from each entry point (issues #703/#704, PR #770) |
| `gapfix/` | The passes below, `scorecard.py`, `pack_standalone.py` (+ `standalone_shim.js`) |
| `gapfix/added_*.json`, `stale_sources.json` | Logs of edges added by the coverage/test passes and of stale doc sources |

## Coverage scorecard (`gapfix/scorecard.py`, target ≥ 90% each)

| Category | Covered / total | % |
|---|---|---|
| files (tracked, non-media) | 4197 / 4215 | 99.6 |
| symbols (Python defs) | 18375 / 18965 | 96.9 |
| imports | 1250 / 1296 | 96.5 |
| calls (production functions in the call graph) | 5461 / 5866 | 93.1 |
| fn_depth (real summary + signature, McCabe, raises, SQL effects) | 18261 / 18412 | 99.2 |
| file_summary | 4249 / 4249 | 100 |
| docs_links (`mcp_server` modules linked to their ADR) | 642 / 698 | 92.0 |
| data_flow (modules with SQL that have reads_from/writes_to) | 79 / 79 | 100 |
| domain (MCP tools + hooks with a flow) | 71 / 71 | 100 |
| knowledge (ADR pages as article nodes) | 900 / 900 | 100 |

Not a graph property and not in the table: real test coverage of the code (76% of
`mcp_server` functions executed by at least one test, coverage.py, 2026-10-20).

## Passes, in the order they were applied

Base: `/understand` (LLM file analysis, layers, tour). Then, from the repository root
(`G=.ua/knowledge-graph.json`):

1. `add_ast_symbols.py`, `link_test_imports.py`, `link_runtime_tested_by.py`,
   `link_ast_calls.py`, `flag_stale_docs.py` — cycle 1 gap fixes (symbols missed by the
   LLM pass, test → code links, stale doc sources).
2. `link_coverage_tested_by.py` — `tested_by` from coverage.py dynamic contexts
   (`pytest --cov-context=test`); `exercisedByTests` on symbols.
3. `link_sql_dataflow.py . $G` — store tables from `CREATE TABLE`, `reads_from` /
   `writes_to` / `defines_schema` from SQL literals.
4. `link_calls_resolved.py . $G` — call graph resolved through imports, re-exports,
   classes, mixins, factory return types and callables passed as references. Rules in
   `call_resolution.py` (modules, imports, classes) and `call_targets.py` (types,
   mixins, per-call targets).
5. `link_adr_citations.py . $G` — `documents` edges ADR → module from `ADR-NNNN` citations.
6. `summaries_from_docstrings.py . $G` — short summaries replaced by the author's docstring.
7. `function_depth.py . $G` — signature, McCabe complexity, raises, SQL effects.
8. `build_knowledge_layer.py . $G` — ADR articles, topics, scientific sources.
9. `compute_impact.py . $G df3a447 .ua/overlays pr770=<ref> ...` — per-function impact
   (`impact`, `blast:*` / `entry:*` tags) and per-PR overlays.
10. `build_domain_graph.py . $G .ua/domain-graph.json` (source readers in
    `domain_sources.py`).
11. `scorecard.py . $G` — the table above.

Each pass is idempotent on the graph it reads (it skips edges already present, and the
knowledge layer is rebuilt from scratch).

## Viewing

First restore the graph: `gunzip -k .ua/knowledge-graph.json.gz` (the plain file is
ignored by `.ua/.gitignore`: at 38 MB it exceeds the 16 MB per-file budget of the HOL
plugin scanner in CI, which then stops the repository's security scan early; a `.gz`
is skipped as binary). After refreshing the graph, re-compress it with
`gzip -9 -n -k -f .ua/knowledge-graph.json` before committing.

- With the plugin: `/understand-dashboard` from the repository root.
- Offline single file: build the dashboard once in single-chunk mode, then
  `python3 .ua/gapfix/pack_standalone.py <dashboard build dir> .ua .ua/overlays out.html`;
  open `out.html` by double-click (graph, domain graph and overlays are embedded; the
  "Impact view" selector switches between PR overlays).

## Refreshing

After code changes, `/understand` updates the graph incrementally from
`fingerprints.json`; re-run passes 3–11 afterwards. The overlays are tied to their PR
branches and to base `df3a447`.
