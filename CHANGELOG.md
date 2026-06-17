# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.22.0] - 2026-06-17

Security + reliability release (P0/P1 audit hardening). PostgreSQL remains the
mandatory backend; the SQLite fallback path was substantially repaired.

### Security
- **Headless authoring sandbox (RCE fix).** The `claude -p` documentation worker
  used `--allowedTools` (an auto-approve list, **not** a restriction), so `Bash`
  stayed in the model's context, and it loaded the target repo's
  `.claude/settings.json`/hooks — letting a malicious repo achieve code execution.
  Now uses `--tools "Read,Glob,Grep"` (removes Bash/Edit/Write from context) **and**
  `--bare` (ignores the untrusted repo's settings/hooks/MCP), and fails closed when
  `ANTHROPIC_API_KEY` is absent. The feature remains default-OFF.
- **Secret redaction.** `redact_url` now masks libpq `?password=`/`pgpassword`
  query-parameter passwords and preserves IPv6 host brackets; `doctor` scrubs
  PostgreSQL DSNs leaked through psycopg exception/`error` fields.
- **Dependency bootstrap.** Removed a false "pip rejects hash mismatch" claim and
  sanitized the pip subprocess environment (`PIP_INDEX_URL`/`PIP_EXTRA_INDEX_URL`/
  `PIP_CONFIG_FILE`/…) so the `--index-url` lock can't be bypassed via inherited env.

### Fixed
- **SQLite backend A3 rename completion.** The `heat` → `heat_base` migration was
  incomplete on the SQLite fallback: `INDEXES_DDL` was a single multi-statement
  string referencing a non-existent `heat` column, so **none of the 11 indexes were
  created** (full table scans); `sqlite_store_search.py` and `sqlite_store_stats.py`
  also queried `heat`. All corrected — recall/ingest on the SQLite fallback is no
  longer crippled. (`entities.heat` is a real column and is untouched.)
- **SQLite parity:** `insert_memory` now persists `supersedes_id`;
  `get_temporal_co_access` honors `min_access` via `access_count`.
- **Ablation:** `Mechanism.COMPRESSION` added to `plan_full_ablation_study()`.
- **Benchmarks:** reproducibility `_git_dirty` uses `git status --porcelain`
  (detects staged + untracked changes).
- **Remote PostgreSQL:** `scripts/setup.py` preflight derives host/port from
  `DATABASE_URL` (`pg_isready -h HOST -p PORT`) instead of always probing localhost.
- Flaky `forget`/`navigate_memory` handler tests fixed at the root (the SQLite test
  cleanup iterated a hardcoded handler list and skipped a WAL checkpoint).

### Added
- **Test coverage (P1-8):** `write_gate`, the anti-data-loss conftest guard, an
  end-to-end PG recall test, MCP handler contract tests
  (`validate_memory`, `get_causal_chain`, `assess_coverage`, `add_rule`, `anchor`),
  and a dedicated SQLite backend suite.
- **CI:** a `test-sqlite` job exercising the SQLite fallback.
- **Docs:** `docs/deployment-scenarios.md` — WSL, TLS client-certificate
  `DATABASE_URL` (no password; passed straight to libpq), and remote PostgreSQL.
- `tasks/pyright-remediation-plan.md` — phased plan to clear the 566 pyright errors.

## [3.21.0] - 2026-06-15

### Changed
- **Visualization extracted to the standalone [cortex-viz](https://github.com/cdeust/cortex-viz) MCP.** The galaxy graph, execution trace, the Knowledge / Board / Wiki / Pipeline views, the HTTP server, the workflow-graph builders, and all `ui/` assets (−50,671 lines) now live in cortex-viz, which reads this same PostgreSQL store **read-only**. Cortex is a focused memory engine again.

### Removed
- **BREAKING:** the `open_visualization`, `get_methodology_graph`, and `query_workflow_graph` MCP tools — now provided by cortex-viz. **46 MCP tools** remain.
- The in-repo `cortex-visualize` skill (moved to cortex-viz, repointed at its tools).

### Notes
- No memory, retrieval, consolidation, or wiki-authoring behaviour changed. Full suite green (3214 passed); `mcp_server` imports cleanly and registers exactly 46 tools with zero viz tools and no dangling references.

## [3.20.0] - 2026-06-13

Consolidated release. Supersedes the never-tagged 3.19.6 prep commit
(`c51d895e`): its launcher self-heal, SSE-only galaxy delivery, and wiki
drift fix are retained under **Fixed** below, joined by the feature batch
that landed afterward.

### Added

- **Codebase graph intelligence.** Leiden community detection, centrality
  and god-node analysis, and native tree-sitter symbol extraction across
  7 languages — no `automatised-pipeline` dependency required for the
  symbol graph.
- **Explicit supersession edges for knowledge updates.** A memory that
  updates prior knowledge now records a typed supersession edge to what it
  replaces; recall tier-sorts the superseding memory above the superseded
  one instead of returning both as peers.
- **MinHash entity-dedup engine.** Near-duplicate entities are collapsed
  via MinHash similarity, with an AST-symbol origin flag distinguishing
  code-derived entities; a mutating consolidate-time entity-merge cycle
  applies the dedup during maintenance.
- **`include_related` recall mode.** An inline relation-walk that returns a
  memory's graph neighbours in a single recall call rather than requiring a
  follow-up `navigate_memory`.
- **Connection-rooted scoping** via `CORTEX_ROOT_AGENT_TOPIC` — roots
  recall/scoping at a configured agent topic.
- **Visualization: node-click orchestrator and uncapped galaxy.** Every
  node kind is clickable with an orchestrated detail fetch; the galaxy node
  cap is removed; causal-chain and working-directory resolution fixed.
  Canvas hit-testing is O(1)-amortized via a uniform-grid spatial hash.

### Fixed

- **Ingestion no longer indexes plugin-cache copies** of a repo (duplicate
  graphs from `~/.claude` plugin mirrors).
- **`ENTITY_DEDUP` registered in the full ablation study** so the new
  dedup mechanism is lesion-testable.
- **CI restored to green** — `ruff format`/lint compliance and the I2
  canonical-writer invariant updated for the heat-writer line shift.
- **MCP server failed to connect forever after an interrupted first
  bootstrap.** An interrupted `pip install --target deps/` (e.g. the MCP
  client's startup timeout killing the first dependency install) left
  package directories without `__init__.py`. Python imports such a husk
  as a namespace package, so the launcher's missing-dep check passed
  while `from fastmcp import FastMCP` died with "unknown location" — and
  because `deps/` is first on `sys.path`, the husk shadowed every
  healthy install on every retry. The launcher now detects husks
  (`module.__file__ is None`), deletes them, and reinstalls; pip runs
  against a temp dir and commits into `deps/` only on success (atomic —
  a mid-install kill can no longer poison the deps dir); pip failures
  are printed to stderr instead of swallowed, and PEP 668
  externally-managed interpreters retry with `--break-system-packages`.
- **Galaxy graph: L6 never finished, nodes weren't browsable, and the
  build looked deadlocked.** Four stacked causes, all in the delivery
  layer: the SSE event stream was closed at baseline (subscribers got
  `done` before a single L6 symbol streamed); the SSE client script was
  never loaded by the page (the polling phase loader was the only
  delivery path); every L6 batch throttled a full second against the
  LayoutAuthority's overload flag, which could never clear because the
  authority has no consumer (~1 h of pure sleep per build); and `_merge`
  rebuilt its dedup state over the whole cumulative cache per 200-node
  batch (O(n²), GIL-pinned for hours, starving all HTTP requests). The
  live SSE stream (`/api/graph/events`) is now the only graph delivery
  path: the build kicks at server launch, every merge emits its delta
  immediately, the stream closes once at true end-of-build, and warm
  processes replay the event buffer. `_merge` is incremental, and
  `/api/graph/node` resolves every node kind via a new id index
  (previously only `memory:`/`entity:` PG ids resolved — symbol, file,
  and domain clicks returned an empty detail panel). Measured: full
  build to `full_ready` in 202 s with 143,816 nodes / 270,707 edges
  incl. 94,437 L6 symbols (previously never finished); node detail in
  ~0.5 ms.
- **Wiki drift no longer flags technology names (`Node.js`,
  `Three.js`) as missing source files.**

## [3.19.5] - 2026-06-12

### Fixed

- **`open_visualization` spawned a new server on a new port (with a cold
  graph rebuild) on every call, leaking ephemeral-port processes.** Two
  root causes: nothing recorded the running instance, and the handler
  ran `launch_server` unconditionally even after the bootstrap had
  already started a server (a double-spawn race). New
  `mcp_server/server/viz_instance.py` keeps an instance registry at
  `~/.cache/cortex/viz-server.json` (`{pid, port, started_at}`); launch
  paths probe it and reuse a healthy, source-current instance
  (source-currency compares the newest source mtime, excluding
  `__pycache__`). Stale instances are stopped with kill-and-wait
  (SIGTERM → wait → SIGKILL, reaping the instance's own zombie children)
  before rebinding. The handler now parses the bootstrap's `url=` line
  and skips `launch_server` when the bootstrap already produced a live
  server. Verified by smoke test: run 1 spawns and registers, run 2
  reuses the same pid.
- **The skeleton-snapshot write clobbered the shared full graph
  snapshot.** The skeleton write in `http_standalone_graph.py` fed a
  nonexistent `/api/graph.bin` route; its only observable effects were
  overwriting the full snapshot (36,931 → 31 nodes) and flipping the
  complete-snapshot counts to `None`, forcing cold rebuilds. Removed.

## [3.19.4] - 2026-06-12

### Fixed

- **`/mcp` showed a failing `cortex` server (-32000) whenever the plugin
  source repo itself was the working directory.** The repo-root
  `.mcp.json` served double duty: plugin MCP config (plugin.json
  referenced it as `"./.mcp.json"`) AND — unintentionally —
  project-scoped MCP config picked up by Claude Code when working in
  this repo. In project scope `${CLAUDE_PLUGIN_ROOT}` is never
  substituted (it is plugin-scope only), so the spawn ran
  `python3 '<repo>/${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py'` → ENOENT
  → "MCP error -32000: Connection closed", shadowing the healthy
  plugin-scoped server (`plugin:cortex:cortex`, which connected in
  ~1.7s in the same session's logs). Fix: the MCP server config moved
  inline into `.claude-plugin/plugin.json` `mcpServers` (documented
  form, plugins-reference) and the repo-root `.mcp.json` was deleted —
  inline plugin config is invisible to project-scope discovery. The
  contract test now reads the inline object and pins the absence of a
  repo-root `.mcp.json`.

## [3.19.3] - 2026-06-11

### Fixed

- **`ingest_codebase` silently truncated every ingest — four wiring bugs
  to the automatised-pipeline upstream, all verified live (RCA
  2026-06-11).** A force-reindexed run on the Cortex repo now lands
  8 106 symbols + 1 234 files (9 340 entities, exact conservation),
  11 680 call + 6 414 containment edges, and 572 process wiki pages —
  vs. ~2 110 symbols / 500 files / 0 wiki pages before.
  1. *Byte-budget pagination ignored.* Upstream ≥0.4.0 pages
     `query_graph` responses (`truncated` + `next_offset`);
     `_run_query` read only the first page, so `iter_call_edges`'s
     `len(rows) < page_size` end-check fired mid-stream (~887/4 669
     call edges per run). `_run_query` now drains the cursor (with a
     non-advancing-cursor guard).
  2. *`LIMIT 500` injection capped LIMIT-less queries.* `fetch_files`
     sent no LIMIT, so upstream injected `LIMIT 500` — 500/1 233 files
     forever. `fetch_files` now pages with explicit SKIP/LIMIT. Dead
     `fetch_top_symbols` (same flaw, zero callers) removed.
  3. *Symbol page stride mismatch.* `_ingest_entities` advanced its
     offset by `page_size` while each label query consumed only
     `page_size // 3` rows — every window skipped the rows between
     (≈2 000 of 3 645 Functions). New `symbol_page_stride()` keeps the
     LIMIT and the stride in one function.
  4. *Process wiki pages keyed on fields that never existed.*
     `get_processes` emits `node_count`/`depth`, never
     `symbols`/`symbol_count`/`bfs_depth`; the renderer read the latter,
     so every process counted 0 symbols and ZERO codebase wiki pages
     were ever written. The reader now uses the verified contract, the
     process list follows upstream pagination, and pages are enriched
     with real participating symbols via `ParticipatesIn_<Label>_Process`
     edges (capped at the renderer's 50-symbol display limit).
- **Entity dedup was domain-blind; insert counts were fabricated.** The
  staging sink's `NOT EXISTS` matched on name alone, so once ANY domain
  held a symbol name, re-ingest under a new domain inserted nothing —
  all code entities stayed credited to a stale `code:3.18.4` domain.
  Dedup now scopes to `(LOWER(name), domain)`; edge endpoint JOINs scope
  to the same domain (preventing cross-domain fan-out) and compare
  against `LOWER(domain)` to match the `normalize_domain()` trigger.
  The response now reports true `entities_written` (sink insert counts)
  alongside `entities_seen` — the old field reported seen-as-written.

## [3.16.0] - 2026-05-13

ADR-2244 reaches its full Phase 2-6 cycle: pilot verification, stable-ID
foundation, redirect mechanics, bulk-migration tooling, default-view
filtering, and both producer audits. The wiki classification redesign
that started in v3.15.4 is now complete code-side; one-shot apply
scripts wait for operator authorisation.

### Added
- **Pilot migration analyzer + 1000-page accuracy verification (Phases 2).** `scripts/wiki_pilot_migration.py` walks the live wiki, runs each page through the post-#27/#28 classifier, and reports the proposed 4-tuple alongside the legacy kind. Live 1000-page sample landed at **96.7% kind-kept** — well above the ≥ 90% ADR-2244 acceptance target. The pilot also drove a calibration pass (Nygard heading skeleton detection for ADRs, `architecture` removed from adr.tag_aliases, security audience tightened to require `cryptograph(y|ic)` not bare `crypto`, `adrs` typo dir mapped to `adr`). ([#31](https://github.com/cdeust/Cortex/pull/31), [#32](https://github.com/cdeust/Cortex/pull/32))
- **Stable page IDs + redirect stubs (Phase 3 foundation).** Every wiki page now carries an immutable `id: <UUID4>` in its frontmatter so renames can leave redirect stubs that preserve inbound links during bulk migration. New modules: `mcp_server.core.wiki_identity` (UUID generation, parsing, validation) and `mcp_server.core.wiki_redirect` (redirect data model, path-based chain resolution with cycle + depth protection, stub authoring). New CLI: `scripts/wiki_backfill_ids.py` (idempotent one-shot that mints IDs on every page lacking one; dry-run by default). Live dry-run shows 9607 pages would receive a fresh id, 1 skipped (no frontmatter). ([#33](https://github.com/cdeust/Cortex/pull/33))
- **Handler-layer redirect mechanics + `wiki_rename` (Phase 3.2).** `wiki_read` now follows redirect chains transparently (≤ 5 hops; cycles and depth-exhaustion surface as errors). `wiki_list` excludes redirect stubs by default; `wiki_reindex` drops them from `.generated/INDEX.md`. New tool `wiki_rename` performs an atomic move + redirect-stub creation; refuses to operate on pages without a stable id or to chain stubs. ([#34](https://github.com/cdeust/Cortex/pull/34), folded onto main via [#36](https://github.com/cdeust/Cortex/pull/36))
- **Bulk migration — deterministic renames (Phase 4.1).** `scripts/wiki_bulk_migrate.py` walks three audit-confirmed pollution patterns and renames them via `wiki_rename`: `.md.md` duplicates (58 paths), `decision-created-YYYY-MM-DDt…z` timestamp slugs (10 paths), and `users-cdeust-…`-shaped path-leak slugs (10+ paths). Live dry-run detects 70 pollution paths in the current wiki, all correctly refused pre-backfill. ([#35](https://github.com/cdeust/Cortex/pull/35), folded onto main via [#36](https://github.com/cdeust/Cortex/pull/36))
- **Bulk migration — file-doc re-bucket (Phase 4.2).** `scripts/wiki_rebucket_file_docs.py` moves the 8,734 `notes/<domain>/<id>-file-*.md` pages produced by `codebase_analyze` to `reference/<domain>/<file-slug>.md` and rewrites the frontmatter to the modern schema (`kind: reference`, `lifecycle: seedling`, `audience: [developer]`, `provenance: auto-generated`, full generator block). Slug is derived from the `file:<path>` tag — canonical even when the on-disk filename was truncated to `98817-file-....md`. Idempotent; collisions resolved via `-<memory_id>` suffix. ([#37](https://github.com/cdeust/Cortex/pull/37))
- **Auto-generated pages filtered from default views (Phase 5).** `wiki_list` excludes pages with `provenance: auto-generated` by default — at the 8,700+ scale these would dominate any listing. Opt-in via `include_auto_generated=true`. `wiki_reindex` groups INDEX.md into two top-level sections ("Human-authored" and "Auto-generated reference"); deterministic output preserved. Both filters share a single per-page frontmatter read to keep listing latency under 500ms on the 9000-page wiki. ([#39](https://github.com/cdeust/Cortex/pull/39))

### Fixed
- **Producer audit — `codebase_analyze` routes to `kind=reference` (Phase 6).** The bare `codebase` tag emitted by `codebase_analyze._build_tags` was not in `reference.tag_aliases` (only `code-reference` with a hyphen was), so every file-doc page routed to `kind=explanation` via the legacy-fallback path — the producer-side root cause of the 8,734-page misroute that Phase 4.2 has to clean up. Adding `codebase` to the alias list closes the leak. ([#38](https://github.com/cdeust/Cortex/pull/38))
- **Producer audit — `wiki_seed_codebase` emits modern kind tags (Phase 6.2).** `_kind_for(rel_path)` used to return legacy kind names (`spec`, `convention`, `lesson`, `note`); the call-site wrote them as `kind:<value>` tags that the classifier never read. Now returns modern kind names that are themselves tag aliases (`adr`, `rfc`, `explanation`), and the tag list emits the bare name plus `imported` (provenance hint) — both forms the classifier picks up. ([#40](https://github.com/cdeust/Cortex/pull/40))

### Security
- **`authlib` 0.7.0 → 1.7.2** — Dependabot alert #4 (CVE-2026-44681 / GHSA-r95x-qfjj-fjj2). Unauthenticated open redirect in `OpenIDImplicitGrant` / `OpenIDHybridGrant` when the `openid` scope is omitted. Cortex is not an OIDC authorization server so the vulnerable code paths are never invoked, but the bump closes the alert and protects downstream applications that vendor Cortex's `uv.lock`. ([#30](https://github.com/cdeust/Cortex/pull/30))

### Notes for users
- **The wiki on disk has not been migrated yet.** All apply scripts are dry-run by default. To realise the cleanup:
    ```bash
    python scripts/wiki_backfill_ids.py --apply            # mint 9607 stable IDs
    python scripts/wiki_bulk_migrate.py --apply            # rename the 70 polluted paths
    python scripts/wiki_rebucket_file_docs.py --apply      # move the 8734 file-docs
    ```
    Each step is idempotent. Every move leaves a redirect stub so inbound links continue to resolve via `wiki_read`.
- **Phase 5 + 6 + 6.2 take effect on next MCP restart.** Phase 5 changes how listings render; Phase 6 + 6.2 fix the producers so new writes go to the right place without further intervention.
- The full migration plan (Phases 1–6, including the parts that landed in v3.15.4) is captured in ADR-2244 inside the methodology wiki. The literature survey backing the schema design is at `docs/research/wiki-classification-survey.md` — GRADE certainty: moderate (strong convergence across 14 surveyed taxonomies, no empirical comparison study).

## [3.15.4] - 2026-05-12

### Added
- **Richer wiki classification — multi-axis schema (ADR-2244 Phase 1).** Replaces the single `kind` axis with a 4-tuple `(kind, lifecycle, audience, provenance) + tags`. The previous taxonomy left 92% of pages in the `notes` catch-all; the audit on 2026-05-12 surfaced 58 `.md.md` pages, 10 timestamp-slug ADRs, 11 path-leak slugs, and 537 classifier-rejectable pages. The new schema gives the classifier 8 kinds (tutorial, how-to, reference, explanation, adr, runbook, rfc, journal), 5 universal + 4 ADR-specific lifecycle states, 5 audience values, and 4 provenance values — with `requires_generator` enforcement for ai/auto-generated content. Backward-compatible: legacy directories (`notes/`, `specs/`, `conventions/`, `lessons/`, `guides/`, `files/`) still readable; `normalize_legacy_kind` maps frontmatter on read. ([#27](https://github.com/cdeust/Cortex/pull/27))
- **Data-driven axis registry — open-world classification.** Every classification axis now loads its valid values from `wiki/_schema/<axis>/<name>.md` markdown files. The Python defaults remain as the bootstrap seed; users add new kinds, lifecycles, audiences, or provenances by writing a markdown file with frontmatter (`patterns`, `tag_aliases`, `default`, `requires_generator`, `applies_to_kinds`). Validation policy is **reject + suggest**: unknown values raise with a `difflib.get_close_matches` suggestion and the exact file path to write to register the value. The classifier dispatches via `match_axis(content, tags, axis, registry)` — pure regex + tag-alias dispatch with zero hardcoded enum names. ([#28](https://github.com/cdeust/Cortex/pull/28))

### Fixed
- **`codebase_analyze` no longer silently truncates at `max_files=500`.** Default is now `0` (no limit). Positive values still cap the walk; ADR-0045 §R2 bounded-memory walk preserved for capped mode. Unbounded mode walks the whole tree but materialises only post-filter survivors (`O(filtered_files)`, not `O(tree_size)`). Discovered when a full-scale bootstrap ran two repos that hit the cap at exactly 5000 files. ([#25](https://github.com/cdeust/Cortex/pull/25))
- **Wiki slug/title leaks (`.md.md`, timestamp-as-title, path-embedded titles).** `wiki_layout.slugify` strips trailing `.md` chains so the six filename builders (`adr_filename`, `domain_page_path`, `wiki_sync`, `draft_compiler`, `ingest_prd`, `ingest_codebase_pages`) no longer produce `.md.md`. `derive_title` rejects YAML metadata key:value lines (e.g. `created: 2026-04-15T09:29:10Z`) and content with embedded `/Users/`, `/home/`, Windows drive paths mid-line. When every candidate line is rejected, returns empty to trigger the deterministic `memory-<hash>` fallback instead of leaking raw content prefixes. ([#26](https://github.com/cdeust/Cortex/pull/26))
- **File-documentation pages no longer routed to `notes/`.** The old `wiki_sync._KIND_TO_DIR` had no mapping for `file` kind, so 7820 file-documentation pages produced by `codebase_analyze` silently fell back to `notes/`. The new sync routes auto-generated codebase content to `reference/<domain>/` with `provenance=auto-generated`. (Task #8, folded into [#27](https://github.com/cdeust/Cortex/pull/27).)

### Security
- **`urllib3` 2.6.3 → 2.7.0** — fixes two high-severity issues that affected the Cortex dependency chain: decompression-bomb safeguards bypassed in `HTTPResponse.drain_conn()` and Brotli partial reads (GHSA-mf9v-mfxr-j63j), and sensitive headers leaked across origins by `ProxyManager.connection_from_url` on cross-host redirects (GHSA-qccp-gfcp-xxvc). ([#24](https://github.com/cdeust/Cortex/pull/24))

### Notes for users
- This release introduces a new schema for wiki page frontmatter. Existing pages remain readable; new writes use the modern 4-tuple. The migration phases (pilot → stable IDs → bulk re-bucketing → cleanup → producer audit) are tracked in ADR-2244 inside the methodology wiki and will land in subsequent releases.
- To register your own classification value, write a markdown file under `wiki/_schema/<axis>/<name>.md`. See `mcp_server/core/wiki_axis_registry.py` docstring for the frontmatter contract.
- The wiki-classification literature survey backing the new schema is at `docs/research/wiki-classification-survey.md`. Citations are inline; the GRADE certainty for the schema design is **moderate** — strong convergence across 14 surveyed taxonomies, no empirical comparison study.

## [3.15.3] - 2026-05-09

### Security
- **python-multipart 0.0.26 → 0.0.27** — fixes a denial-of-service vulnerability in `MultipartParser` header parsing where an attacker could send unbounded multipart part headers (oversized individual values or many repeated headers without terminating the header block) causing CPU exhaustion. Affects FastMCP and any ASGI / Starlette / FastAPI app in the dependency chain. Patched version 0.0.27 enforces default header-count and header-size limits. ([Dependabot alert](https://github.com/cdeust/Cortex/security/dependabot))

### Fixed
- v3.15.2 GitHub release was tagged at the wrong commit (308ed41 instead of the PR-#22 merge commit 6b19ec4) due to a local fast-forward conflict during release scripting. The v3.15.2 tag now exists as a graveyard entry; v3.15.3 is the canonical version that includes both the MCP startup robustness work from PR #22 (originally intended for v3.15.2) AND this security bump.

### Notes for users
- If you're on v3.15.0, v3.15.1, or v3.15.2, upgrade directly to v3.15.3 to get the python-multipart security fix plus the MCP startup robustness improvements (`${CLAUDE_PLUGIN_ROOT}` substitution + `cortex-doctor mcp` diagnostic).

## [3.15.2] - 2026-05-09

### Fixed
- **MCP startup robustness** — Discord user reported the Cortex MCP server
  failing to start with no actionable error. Root cause: `.mcp.json` used a
  fragile `python -c` one-liner that read `~/.claude/plugins/installed_plugins.json`
  to dynamically resolve the install path. The wrapper swallowed all
  launcher startup errors invisibly and broke under: (a) plugin upgrade
  leaving stale `installPath`, (b) custom marketplace install names, (c)
  `python3` not on PATH, (d) any `installed_plugins.json` shape change by
  Claude Code. `.mcp.json` now uses `${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py`
  — Anthropic's documented plugin substitution variable, already used by
  every hook in this repo. The launcher self-orients via `__file__` so
  manual installs continue to work.

### Added
- **`cortex-doctor mcp`** — new diagnostic subcommand for end-to-end MCP
  startup checks. Tells the user *exactly* which check failed, what
  command/path was tried, and the actual error string — no more silent
  "✘ failed". Checks: python interpreter on PATH, `installed_plugins.json`
  shape, `CLAUDE_PLUGIN_ROOT` env, launcher smoke probe (catches errors
  the old `-c` wrapper hid), `DATABASE_URL`, critical Python deps. Use
  `--json` for Discord-paste-friendly output.

### Verification
- 36 new tests added (`tests_py/test_doctor_mcp.py`,
  `tests_py/scripts/test_launcher_resolution.py`); all pass.
- Backward-compatible: `cortex-doctor` (no subcommand) preserves legacy
  full-setup verification behaviour.
- Platform-agnostic: no Windows/Mac-specific code paths.

## [3.15.1] - 2026-05-05

### Fixed
- **#16** `seed_project` purged memories tagged `seeded` globally, ignoring the `domain` argument (Coase boundary scope). `delete_memories_by_tag` now accepts an optional `domain` parameter; `seed_project` passes it through. Also auto-detects domain from directory name when caller omits it. Reported by PSGSupport.
- **#17** `remember`, `recall`, `get_telemetry` returned `'structured_content must be a dict or None. Got str'` from FastMCP despite the underlying ops succeeding (Liskov contract violation). Root cause: `safe_handler` JSON-encoded every return value globally; the bug surfaced only on handlers declaring `outputSchema`. Fix returns dicts directly; new contract-enforcement test introspects every registered tool. Reported by PSGSupport.
- **#18** `query_methodology(cwd="C:/Users/...")` returned a hollow profile because the slug generator only handled POSIX paths (Hopper cross-platform abstraction leak). Path normalization now detects path syntax (not `os.name`), accepting Windows forward-slash, Windows backslash, and Git-Bash drive translation forms. Idempotent: existing slugs round-trip to themselves. Reported by PSGSupport.
- **#20** `auto_recall` hook queried non-existent `memories.heat` column instead of `heat_base`, failing silently on every UserPromptSubmit (Feynman integrity audit). Fix uses `effective_heat(m, NOW())` PL/pgSQL function for lazy-decay semantics. Audit also caught and fixed 4 sister bugs in `session_start.py` and `agent_briefing.py`. New schema-integrity test parses every static SQL blob in hooks/handlers and asserts column existence. Reported by PSGSupport.
- **#19** Dockerfile `ENTRYPOINT ["neuro-cortex-memory"]` referenced a console script not registered in `pyproject.toml`; the image failed to start. Switched to `python -m mcp_server` (the documented invocation in `mcp_server/__main__.py`). Reported and fixed by PSGSupport.

### Verification
- 2669 tests pass on Mac (full regression sweep).
- Liskov handler-contract test (3 cases) and Feynman schema-integrity test (27 SQL blobs audited) added as abstraction barriers preventing recurrence.
- All fixes platform-agnostic; no Mac/Linux regression.

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
