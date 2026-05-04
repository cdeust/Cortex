# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.15.0] — E1 v3 verification campaign + arXiv-ready papers + BEAM-10M harness

A single coherent release covering 64 commits since v3.14.12. The headline is
verification: every benchmark number on the README is now backed by a
per-mechanism ablation row with code SHAs, dirty flags, manifests, and
per-row JSON outputs preserved alongside the writeups. Two production fixes
were surfaced by the campaign and ship inside the same release. Both
companion papers (thermodynamic memory + structured context assembly) are
arXiv-ready.

### Verification campaign (paper-claim-bearing)

- **E1 v3 LongMemEval-S — 17-row per-mechanism ablation, n=500.** Headline
  `MRR = 0.9124`, `R@10 = 98.4%` (vs. published baselines `MRR = 0.882`,
  `R@10 = 97.8%`: **+3.0% MRR, +0.6% R@10**). Driver:
  `benchmarks/lib/run_e1_v3_lme.py`. Per-row JSONs:
  `benchmarks/results/ablation/longmemeval-s_v3/`. Writeup:
  `tasks/e1-v3-results.md`.
- **E1 v3 LoCoMo — 14-row two-baseline ablation, n=1986.** Headline
  `MRR = 0.8279`, `R@10 = 94.3%` (`BASELINE_NO_CONSOLIDATION`,
  longitudinal-read-path anchor) — vs. CLAUDE.md baseline
  (`MRR = 0.794`, `R@10 = 0.926`): **+4.3% MRR, +1.7% R@10**. Re-run on
  plasticity-fixed bytes (commit `2f45bcb`, descendant of `5f737fe`).
  Cadence-fix anchor agreement re-validated identically
  (`ΔvsNO = +0.0014`); two consolidation-only rows
  (`HOMEOSTATIC_PLASTICITY`, `SCHEMA_ENGINE`) recover positive
  contributions previously masked by the contract bug.
  `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/`.
  Writeup: `tasks/e1-v3-locomo-results-post-fix.md`. The pre-fix sweep is
  preserved at `tasks/e1-v3-locomo-results.md`.
- **Phase A + B blend-weight calibration.** Central composite design + 5×5
  grid search; all six post-WRRF rerank constants confirmed near-optimum at
  the engineering defaults shipped today. `tasks/e1-v3-blend-calibration.md`.
- **Per-category delta analysis (LME-S).** Mechanism specialization
  surfaced: HDC specializes for multi-session reasoning, HOPFIELD for
  knowledge updates, ADAPTIVE_DECAY against stable preferences.
  `tasks/e1-v3-per-category.md`.

Total: **45 per-mechanism evidence rows** across 26 enum mechanisms
(17 read-path on LongMemEval-S + 9 consolidation-only routed to LoCoMo).

### Fixed (production fixes surfaced during verification)

- **`6c51bce` — consolidation cadence is now ingest-relative.**
  `consolidation_engine` migrated from wall-clock `created_at` to
  ingest-relative `ingested_at`. Recovers `MRR 0.222 → 0.8264` on
  backdated corpora; affects every production backfill scenario where
  memories carry old timestamps but were written today.
- **`5f737fe` — plasticity result-shape contract preserved on ablation.**
  `apply_hebbian_update` no-op (when `CORTEX_ABLATE_SYNAPTIC_PLASTICITY=1`)
  now returns dicts with `action="none"` instead of raw edge tuples,
  fixing a silent `KeyError` downstream in consolidation/plasticity. This
  is what was masking the two consolidation-only contributions in the
  pre-fix LoCoMo sweep.

### Added (read-path mechanisms now wired end-to-end)

- **`ddb5b58` / `024ea1a` / `bc0ae4f`** — `HOPFIELD`, `HDC`,
  `SPREADING_ACTIVATION`, `DENDRITIC_CLUSTERS` wired into the `pg_recall`
  pipeline. Batch Hopfield embeddings and real entity-set Jaccard for the
  dendritic stage. Query-entity resolution extended to natural-language
  tokens.
- **`81e8d90`** — `EMOTIONAL_RETRIEVAL` + `MOOD_CONGRUENT_RERANK` are now
  live read-path stages (not test-only).
- **`9d6bc96`** — `RECONSOLIDATION` post-retrieval stage wired
  (Nader 2000); retrieved memories become labile and may be updated
  against the retrieval context.
- **`c5ade6b`** — VADER → `user_mood` EMA hook in `remember()`; closes
  the `MOOD_CONGRUENT` signal gap end-to-end.
- **`b4b23e7`** — `PgMemoryStore.get_user_mood` / `set_user_mood` +
  `user_mood` DDL; the column the read-path stage was reading didn't
  exist before this.
- **`099ba1e` / `54f8501`** — 23 mechanisms now have
  `CORTEX_ABLATE_<MECH>=1` env-var hooks reading at the production
  hot-path (not just at test wiring), so ablation studies exercise the
  same code path as production.

### Added (benchmark + verification infrastructure)

- **`3201cc3` / `0a53996`** — BEAM-10M LLM head-to-head harness scaffold
  + live mode wiring at `benchmarks/llm_head_to_head/`; smoke pending
  API keys.
- **`0e1f90d`** — LongMemEval-S `--with-consolidation` flag.
- **`b68c5ac` / `ef178da`** — LoCoMo `--ablate` + `--with-consolidation`
  + `--results-out` flags + 14-row driver `run_e1_v3_locomo.py`.
- **`f09485d`** — Blend-weight calibration infrastructure with
  pre-registration; harness dirty-check matched to pre-reg
  (`39ab694` ignores submodule internal state).
- **`5a5d8d3` / `3eab1ed`** — E2 N-scan rebuilt as real-benchmark
  subsample + Zipf synthetic; ablation env vars wired into the
  production code path.
- **DB snapshot + restore + HNSW determinism infrastructure** (E2 / E3 /
  E4 / E5 internal harnesses).

### Added (papers + endorsement materials)

- **`6b80760` / `3ace1fb` / `3eaeaf6`** — `docs/arxiv-thermodynamic/main.pdf`
  compiled, 30 pages. Ported to LaTeX matching `arxiv/main.tex` style.
- **`9e6ddf6`** — Recompile with bibtex pass; **all 45 citations now
  resolve** (vs. the previous 4 unresolved `??` markers).
- **`bce4840` / `db4fe0a` / `6f75221`** — §6.3 three-pass integration:
  LME-S evidence + LoCoMo subsection + post-fix re-run + cadence-fix
  narrative + plasticity-fix narrative.
- **`fa9c101` / `fb6f67f`** — §6.4 Operating Regime added; full E2b Zipf
  curve integrated; falsifications reframed as predicted boundaries with
  the `N=100k` datapoint landed.
- **`a787fe6`** — Refresh `linkedin-endorser-post.md`; new
  `arxiv-endorsement-email.md` template with pre-submission checklist.
- **`974c364` / `2152946`** — Prose polish; `BEAM Overall 0.543 → 0.591`
  number fix in CLAUDE.md and the markdown source.
- **`ffcad91`** — Repo reorg: `arxiv/` → `arxiv-context-assembly/` +
  paper-md moved into `docs/papers/`.
- **`docs/arxiv-context-assembly/main.pdf`** — 37 pages, pre-existing
  verbatim + argmax bugs fixed, arXiv-ready.

### Fixed (issue fixes from contributors)

- **`5398745`** — issue #15 (Nitjsefnie). `discover_files` walks all four
  session layouts (subagent + teammate transcripts), recovers ~89% of
  session content during backfill that was previously dropped.

### Fixed (CI + plumbing)

- **`df14e16`** — DDL comment semicolon broke `ddl.split(';')` extractor.
- **`9f94bd3`** — `user_mood` DDL comment semicolon + test uses dominant
  beta.
- **`34aa452`** — Repair docstring boundary in `cls.run_cls_cycle`
  (broken in `3eab1ed`).
- **`51ce608` / `c4253cc` / `5271828` / `fd51f6f` / `4918638` / `79f0b20`** —
  ruff format + drop unused imports in verification harnesses;
  bump tool count to 47.
- **`18b4be4`** — ruff format on `memories_page` + `memories_facets`.

### Changed (visualization, repo housekeeping)

- **`63bacca` / `2953bae` / `b7a8f97`** — Paged Knowledge + Board with
  filter chips, lazy-load; default landing reverted to Knowledge; Graph
  view restored to pre-d3-removal state with a warning banner.
- **22 stale public repos archived; `ai-prd-mcp` deleted** — security
  hardening (legacy build artefacts had embedded keys at one point) +
  portfolio cleanup.
- **`551a411` / `30d80fe`** — Profile README draft for `cdeust/cdeust`
  (controls AI Overview narrative); profile draft points
  `AI Architect` to website not archived repo.
- **Cortex repo description + topics refreshed** for AI-search
  discovery.

## [3.14.12] — fix MCP client deadlock on long upstream responses

### Fixed

- **`ingest_codebase` hung indefinitely on polyglot repos.** Two
  deadlock vectors in `mcp_client.py`:

  1. `_read_loop`'s `except Exception: pass` silently swallowed any
     stream-level failure (`LimitOverrunError`, `IncompleteReadError`,
     `ConnectionResetError`, `BrokenPipeError`, JSON-side bugs). When
     the reader exited, every pending request future stayed pending
     forever — `_send`'s `await future` blocked the caller indefinitely.
     Reader now rejects every pending future with a
     `McpConnectionError` carrying the terminal cause, so callers
     surface a clear error instead of hanging.

  2. `_send` honoured `callTimeoutMs: 0` as "no timeout at all"
     and called `await future` unbounded. Combined with the silent
     reader death, this guaranteed deadlock on any upstream that
     emitted >limit bytes on a single line or terminated without
     responding. We now enforce a 60-minute hard ceiling even when
     the operator opts into "no timeout" — well above any legitimate
     codebase indexing job (largest observed production runs are
     ~12 minutes), low enough that a wedged upstream surfaces.

- `_read_loop` now logs non-JSON lines instead of silently dropping
  them, so future protocol-level mismatches become visible without
  crashing the loop.

## [3.14.11] — track automatised-pipeline binary rename + fix pool allowlist

### Fixed

- **`ingest_codebase` failed with `Command 'ai-architect-mcp' not in
  allowed list`.** The pool path in `mcp_client_pool.get_client()`
  instantiated `MCPClient` without injecting `_extra_allowed_commands`,
  while the bridge path in `ap_bridge.py` injected `{"node",
  "automatised-pipeline", "ai-architect-mcp"}` before connecting. The
  `ingest_codebase` codepath went through the pool, so the upstream
  binary was rejected by the base allowlist
  (`['cortex', 'mcp-server', 'node', 'npx', 'python', 'python3']`).
  Pool now mirrors the bridge's extension.

### Changed

- **Track upstream binary rename** (`automatised-pipeline` ≥ v0.0.7):
  the upstream Rust binary is now named `automatised-pipeline` (was
  `ai-architect-mcp`). Updated:
  - `pipeline_installer.py`: `--bin automatised-pipeline` and
    `_BUILT_BINARY_REL = "target/release/automatised-pipeline"`.
  - `pipeline_discovery.py`: dropped legacy `ai-architect-mcp` from
    `_BINARY_CANDIDATES`; `_BUILT_RELATIVE` updated.
  - `pipeline_install_release.py`: release-asset naming convention
    follows upstream (`automatised-pipeline-{os}-{arch}.tar.gz`).
  - `ap_bridge.py`: dropped `ai-architect-mcp` from
    `_extra_allowed_commands` (only `automatised-pipeline` + `node`).
  - `http_launcher.py`, `http_standalone.py`: binary discovery uses
    the new name.

### Migration notes

- Users running the upstream pipeline must update to v0.0.7 of
  `cdeust/automatised-pipeline` (binary renamed). Cortex's source
  build path (`pipeline_installer`) and prebuilt fast-path
  (`pipeline_install_release`) both target the new name.
- Existing installs at `~/.claude/methodology/bin/mcp-server` keep
  working — the symlink target is rebuilt on next install.

## [3.14.10] — self-locating plugin MCP launcher

### Fixed

- **`plugin:cortex:cortex` failed to connect from any non-Cortex CWD.**
  The plugin's `.mcp.json` relied on Claude Code injecting
  `CLAUDE_PLUGIN_ROOT`, which was not happening reliably; the
  `${CLAUDE_PLUGIN_ROOT:-$PWD}` fallback resolved to the user's project
  directory, where `scripts/launcher.py` does not exist. Replaced the
  bash command with a Python one-liner that reads
  `~/.claude/plugins/installed_plugins.json` (always at a fixed absolute
  path) to discover the plugin install path, then `execvp`s
  `launcher.py`. No CWD or env dependency. Users in any project now get
  Cortex on plugin update — no per-project configuration required.

## [3.14.9] — ingest_codebase: no caps + Rust-style qn fallback

### Fixed

- **Hardcoded `top_symbols=50` / `top_processes=10` caps in the FastMCP
  wrapper** (`mcp_server/tool_registry_ingest.py`) silently truncated
  every ingest to the longest 50 symbols across Function/Method/Struct,
  regardless of the schema's documented `null = unlimited` default. On
  the Cortex codebase this collapsed an upstream graph of 197 646
  nodes / 95 185 edges to **98 memories / 98 entities / 3 edges**.
  Removed both parameters from the tool wrapper signature; the
  composition root now always passes `None` so the handler pulls every
  Function/Method/Struct/process the upstream graph holds.
- **`fetch_files` shared the symbol cap.**
  `cypher.fetch_files(graph_path, limit=top_symbols)` truncated File
  nodes to the same slice as the symbol cap. With `top_symbols=50`,
  only 50 of thousands of files came back; the
  `(:File)-[]->(:symbol)` containment join filtered by
  `known_files` and dropped every edge whose file wasn't in that
  50-file slice. Decoupled: files are pulled unconditionally
  (`limit=None`); only symbols may be capped (and even that path is
  no longer reachable from the public tool).
- **`file_path_from_qn` couldn't resolve Rust-style qualified names.**
  First-party Python in this codebase emits
  `mcp_server::handlers::ingest_codebase::handler`, which the previous
  fallback split on `::` and returned `"mcp_server"` — not a real
  file path, so containment failed and the diagnostic blamed a
  "non-Python indexer". Rewritten to return a priority-ordered list
  of candidates covering three qn formats:
  `<file.py>::<sym>`, `<dotted.module>::<sym>`, and
  `<a::b::c>::<sym>` (Rust-style module paths). The handler picks the
  first candidate present in `known_files`; the diagnostic now
  describes the actual cause when no candidate matches.

### Changed

- `ingest_codebase` MCP schema no longer advertises `top_symbols` or
  `top_processes` properties. The handler still accepts them as
  programmatic kwargs for tests, but they are not part of the public
  tool surface.

## [3.14.8] — ingest_codebase full-chain extraction + audit fixes

### Fixed

- **`ingest_codebase` extracted only the tip of the iceberg.** BM25
  keyword search (`search_codebase`) was the primary symbol-extraction
  path, returning 2 hits when invoked with the project name as query.
  The Cypher fallback was gated on empty results (`if not symbols_raw`),
  so a 2-hit BM25 response prevented the structural pull. Even when
  the fallback ran it didn't extract `file_path` (Function nodes carry
  no such property — it's encoded in `qualified_name`) or any edges
  (BM25 result rows have no `calls` / `imports` keys). User-visible
  result on a 6 000-symbol codebase: 2 symbols, 0 edges, 0 files.
  Replaced with a Cypher-driven projection that pulls every
  Function / Method / Struct, every File node, every
  (`Function`/`Method`/`Struct`)→(`Function`/`Method`/`Struct`) call
  edge, and every File→symbol containment edge. Live measurement on
  the Cortex codebase: 50 150 symbols, 4 072 files, 30 818 calls,
  19 297 contains.
- **Cache poisoning in `ensure_graph`.** When `analyze_codebase`
  returned `status=error` after the self-heal retry, the handler
  synthesised `<output_dir>/graph` and memoised it as success. Future
  ingests reused the bogus path and silently projected an empty graph,
  indistinguishable from "empty codebase". Now raises
  `McpConnectionError` and refuses to memoise on persistent error.
- **Broad `except Exception → return []`** swallowed every transport,
  parse, and schema error in cypher fetchers as an empty result —
  indistinguishable from "graph genuinely has zero rows". Narrowed to
  `(McpConnectionError, ValueError, KeyError, TypeError)`. Per-query
  failures now surface as a `diagnostics` array in the handler
  response.
- **qualified_name overload collisions** silently dropped legitimate
  cross-overload call edges via the `src_id == dst_id` self-loop
  guard. `write_symbol_entities` now detects collisions and surfaces
  them as diagnostics (the upstream graph itself is the dedupe
  boundary, so downstream disambiguation requires signature data the
  upstream does not emit).
- **Hardcoded `top_symbols=50` / `top_processes=10` caps.** Defaults
  are now `null` ⇒ pull every symbol / every process. Callers can
  still cap explicitly.

### Changed

- **File attribution is now language-agnostic.** Symbol → file mapping
  is derived from authoritative `(:File)-[]->(:symbol)` containment
  edges; the `qn.split("::")[0]` heuristic is demoted to a fallback
  validated against the known-files set, so Rust qualified_names
  (`crate::module::Type::method`) cannot fabricate fake "crate" file
  paths.
- **Server-side filter pushdown** in cypher fetchers: label-OR pattern
  `(b:Function|Method|Struct)` removes Function→Process /
  Function→Community noise from the wire. Single label-OR query for
  containment instead of three round-trips.
- **Stable ordering** for unbounded fetches (`ORDER BY qualified_name`)
  and bounded fetches (`ORDER BY (end-start) DESC`).
- `ingest_codebase.py` split into six modules to fit the project's
  300-line cap: `_cypher` (Kuzu fetchers), `_writers` (MemoryStore
  writers), `_graph` (analyze + cache resolution), `_pages` (process
  wiki rendering), `_schema` (MCP tool schema), and the composition
  root.

### Added

- `_store` singleton lock-guarded for thread-pool callers.
- New tests: `test_persistent_upstream_error_does_not_poison_cache`,
  `test_cypher_error_surfaces_as_diagnostic`,
  `test_file_attribution_uses_containment_not_qn_split`. Mock routing
  rewritten to use regex patterns instead of substring keys
  (substring-prefix collisions silently routed wrong replies).
- Public-readiness baseline (carried from Unreleased): CONTRIBUTING.md,
  CODE_OF_CONDUCT.md, SECURITY.md, GitHub issue/PR templates, expanded
  LICENSE with ecosystem-context preamble + explicit
  independent-authorship statement.
- `prd-spec-generator` cross-link in companion-projects section.

### Fixed (carried)

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
