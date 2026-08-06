# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- **Capture and write-gate bypass are decided by the channel, not the content
  (issue #365).** Fetched web content could install itself in durable,
  cross-session memory by shaping itself. Two decisions read attacker-supplied
  text: `hooks/post_tool_capture` keyed WebFetch/WebSearch capture on a keyword
  match over the fetched output, so a page decided whether it was persisted; and
  `core/write_gate.determine_bypass` grants `bypass_error`/`bypass_decision`
  from the content itself, so text merely shaped like an error or a decision
  skipped the novelty REJECT. `hooks/session_start` then replays stored memories
  verbatim into later sessions. Capture for those tools is now a fixed length
  floor identical for any payload, and the new `core/capture_origin` resolves
  the origin from the producing tool name — known out-of-band, unforgeable by
  the payload — so network-origin content is refused the two content-derived
  bypasses. `force` and a `deliberate` write class are out-of-band human
  signals and remain valid at any origin; the `important`/`critical` tag bypass
  also remains, because `_build_tags` never derives those from output.
  Unrecognised tools classify as `unknown` rather than trusted, so a newly
  added tool is visibly unclassified. `origin_tool` is a declared input on
  `remember` and exposed on both registered MCP wrappers.

  The origin is persisted to a new `memories.capture_origin` column (both
  backends, with a one-shot migration) so the value that governed the gate is
  queryable afterwards — an in-flight-only check cannot be audited, and the
  injection-time critique (#363) and `/why` both need to read it. The upgrade
  path was verified old-code-to-new-code against PostgreSQL: table and the
  `current_memories` view both gain the column, pre-existing rows survive and
  backfill to `unknown`. That view is `SELECT * FROM memories`, whose column
  list PostgreSQL freezes at creation, so `get_all_ddl` ordering
  (migrations before the view) is load-bearing and now has a test.

  The value is queryable by SQL on both backends but is deliberately NOT added
  to recall results yet: `_WRRF_CONTRACT_FIELDS` pins the injected-candidate key
  set to the exact `RETURNS TABLE` column set of the `recall_memories()`
  PL/pgSQL function, so surfacing it on the spreading-activation path alone
  would create the divergence that contract exists to prevent. Carrying it onto
  recall results means changing that stored function's signature, which belongs
  with #363 — the consumer that needs it — so the change and its consumer are
  tested together.

  Note the two neighbouring modules deliberately not reused: `core/provenance`
  grades reference verifiability and `core/source_monitoring` attributes
  epistemic origin, both by reading the content. A hostile page dense with file
  paths and URLs grades `verified` and classifies `perceived` — the most
  credible value in each — so neither can carry a security property.


### Fixed

- **`forget` now deletes across every substrate that holds the content
  (issue #366).** PRIVACY.md told users "The `forget` tool deletes individual
  memories", but a hard delete issued a single `DELETE FROM memories`: the raw
  full text of an oversized auto-capture stayed on disk in its content-addressed
  artifact (`artifact_store` had no removal path at all), and wiki claim events
  derived from the memory survived with `memory_id` nulled by
  `ON DELETE SET NULL`. A hard delete now removes the row, the derived claims,
  and the artifact, reporting `artifact_deleted` / `claims_deleted` in its
  result. Two behaviours are deliberate and asserted: an artifact shared by a
  still-live memory is kept (content addressing dedups identical output to one
  file, so unconditional removal would strip the survivor's content), and a
  `soft=true` delete retains the artifact because it is recoverable by design.
  Deletion ordering is load-bearing in both directions — claims must go before
  the row (the FK nulls the link) and the artifact reference count must be taken
  after it (or the memory counts itself) — and each ordering has its own test.
  PRIVACY.md now states the exact scope, including both exceptions.
- **The artifact pointer format has one definition (issue #366).** It was
  duplicated as an f-string in `hooks/post_tool_capture` and
  `handlers/backfill_helpers`, so no reader could parse it safely. Both writers
  now call `core.gist_extraction.format_artifact_pointer`, with
  `parse_artifact_pointer` as its inverse; the round trip is tested for paths
  containing spaces and for malformed pointers, which resolve to "no artifact"
  rather than a guessed path.

### Added

- **Native Codex local plugin packaging.** A dedicated
  `cortex-codex-plugins` repository marketplace now exposes an isolated,
  MCP-only Codex package backed by the published PyPI stdio server on the
  exact 10-tool `lean` profile. Its 180-second startup ceiling is backed by a
  clean-cache `uvx` lifecycle measured at 110.46 seconds locally (macOS 26.5.1
  arm64, uv 0.8.19) and 23.87 seconds on `ubuntu-latest` CI. This is additive:
  Claude Code remains the primary integration and keeps its primary plugin
  manifest, complete profile, lifecycle hooks, custom agent, and installation
  path unchanged. Its shared marketplace catalog changes only for the
  visualization-plugin migration described below.
- **Breaking visualization-plugin publication rename, with migration shim.**
  The canonical Claude Code publication is
  `hypermnesia-mcp-viz@cortex-plugins` 3.0.0, sourced from the unchanged
  `cdeust/cortex-viz` repository at exact commit
  `1c1940e278979f35cdecea6146d7fb5f749907e9`. Existing installs must uninstall
  `cortex-viz@cortex-plugins`, refresh `cortex-plugins`, and install
  `hypermnesia-mcp-viz@cortex-plugins`. The former identity remains as a
  frozen 2.8.0 migration shim that only prints those instructions; it
  registers no MCP server or tools. Claude's composed tool names also change:
  `mcp__plugin_cortex-viz_cortex-viz__open_visualization` becomes
  `mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__open_visualization`,
  and `mcp__plugin_cortex-viz_cortex-viz__get_methodology_graph` becomes
  `mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__get_methodology_graph`.
  Current companion tables, MCP examples, and API/module documentation now use
  `hypermnesia-mcp-viz` and `ai-architect-mcp-spec`; retired names remain only
  in explicit migration or historical material.
- **Hook-free MCP protocol and host-configuration gates.** CI now starts the
  installed production stdio entry point under representative Claude, Gemini,
  and Codex client identities, completes the MCP lifecycle for both the full
  and exact 10-tool lean profiles, and executes a real SQLite-backed
  `memory_stats` call.
  Separate pinned vendor CLIs parse the Claude plugin, Gemini extension, and
  recommended Codex configuration. These are protocol/configuration contracts,
  not a claim of authenticated model-turn E2E coverage in each vendor UI.

### Changed

- Benchmark provenance now requires the date, environment, exact command, code
  revision, and experimental conditions alongside before/after measurements.
- Claude's wiki-groomer agent now lives in a Claude-specific manifest path,
  preventing Gemini CLI from auto-loading Claude-only agent frontmatter while
  preserving the Claude plugin behavior and tool list.
- The documented PyPI policy changes from a deprecated legacy channel to the
  best-effort hook-free compatibility channel for local stdio hosts, while
  Claude Code's marketplace integration remains primary. The README also
  distinguishes those local hosts from ChatGPT web and documents Codex CLI's
  shared local configuration.

### Fixed

- **A deeply nested source file no longer fails the whole indexing run.** Every
  full-tree AST walker in the extractor layer recursed once per AST level and
  raised an uncaught `RecursionError` past a depth of ~1003 (default recursion
  limit 1000) — reachable on the minified and generated sources found in
  third-party repositories, and fatal for the entire repository rather than the
  one file, since nothing in `mcp_server/` catches it. Seven walkers now use an
  explicit stack: `_walk_type` and `_walk_for_calls` (Python/JS/shared),
  `_walk_java`, `_walk_kotlin`, `_walk_csharp`, `_walk_ruby`, `_walk_php` and
  `_extract_swift_node`. Traversal order is unchanged, verified differentially
  against the previous implementation over 2229 real and synthetic sources with
  zero output differences, including dictionary key order.
- FastMCP's banner-time network update probe can no longer abort stdio startup
  before MCP `initialize` when a SOCKS proxy is configured without optional
  HTTP SOCKS support. The diagnostic banner and its existing user setting are
  preserved; only network version discovery moves outside the runtime
  handshake. Cortex and its dependencies remain explicitly upgradeable through
  the package manager and reproducible through `uv.lock`.

## [4.17.2] - 2026-08-02

### Fixed

- **The ML stack never installed on current pip, silently degrading recall to
  first-stage scores** — `scripts/launcher_deps_install.py`. `ensure_all_deps`
  passes `BASE_PACKAGES` verbatim as the `-c` constraints file
  (`launcher_deps.py:318`), and one entry carries an extra —
  `psycopg[binary]==3.3.4` (`launcher_pins.py:89`). pip has always documented
  constraints files as version-only and now rejects extras outright, so the
  whole ML resolve aborted with `ERROR: Constraints cannot have extras`:
  `sentence-transformers` and `flashrank` never landed. Nothing surfaced the
  failure — only the ML install passes constraints, so the base stack
  installed clean and the FlashRank re-ranker was simply absent, the same
  observable shape as the 2026-07-10 FlashRank incident. `pip_install` now
  normalizes every constraint through the new `constraint_without_extras`
  before writing the file, which restores the parameter's own documented
  contract (its docstring already promised `name==ver`) rather than changing
  it: a constraint pins the VERSION a shared transitive resolves to, and pip
  applies it to the distribution however its extras were requested — the
  install target still carries `[binary]`. Measured 2026-08-02 on pip
  26.0.1 / Python 3.14.4 and reproduced on pip 25.2 / Python 3.13, so the
  affected range is not pip-26-only; both accept the stripped file
  (`pip install --dry-run --no-index -c <BASE_PACKAGES>`).

## [4.17.1] - 2026-08-02

### Fixed

- **The release workflow's test gate now carries ci.yml's network hardening, and v4.17.0's contents ship under this version** — `.github/workflows/release.yml`. v4.17.0 was tagged but **published nothing**: its `test` job hung and blocked all five downstream publish jobs, so no GitHub release, PyPI upload, or `.mcpb` bundle exists for it. Root cause is a trigger asymmetry, not a flake: `ci.yml` fires on `push: branches: [main]` + `pull_request` (ci.yml:4-8), so **a tag never reaches it** — every network-hardening pass CI absorbed since 2026-07-27 silently skipped `release.yml`, while both files kept running the same suite. Run 30741657854 is what that divergence cost: `test_recall_real_spell_by_name` → `pg_recall.py:443` → `reranker.py:109` → FlashRank's bare `requests.get(..., stream=True)`, which **carries no timeout**, so a stalled connect hung in `sock.connect` until pytest-timeout killed the suite — on a tree that had just passed 20 green checks on PR #334. `HF_HUB_OFFLINE` does not reach FlashRank's own fetch path, and `reranker.py`'s `except Exception` cannot engage against a hang that never raises. The `test` job now mirrors ci.yml:103-115,142-195 one-for-one — cache `~/.cache/flashrank` (matching `reranker_model.py:104-113`'s `reranker_cache_dir()`, which honours `$XDG_CACHE_HOME`), prefetch the reranker via `ensure_reranker_loaded()` asserting `state == 'loaded'` so a failed fetch fails the step instead of resurfacing as first-stage-only recall scores (the 2026-07-10 FlashRank incident), harden the HF prefetch to 5 retries with backoff and **drop `continue-on-error`** so a blip cannot leave the cache empty and cascade into a misleading failure, and run pytest under `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` / `CORTEX_RERANKER_OFFLINE` so no download can happen mid-suite. ci.yml's three tree-sitter steps are **deliberately not ported**: `requirements/release.txt` omits tree-sitter and tree-sitter-language-pack (as it omits igraph, leidenalg and texttable), so the AST tests skip in this job and there is no grammar to fetch — porting them would have failed on ImportError. The corollary is recorded in the workflow itself: this gate tests a **narrower surface than CI**, and the three steps must follow if `release.txt` ever gains that dependency. Shipped as a new patch version rather than by moving the `v4.17.0` tag, because a tag executes the `release.yml` of **its own tree** — re-running v4.17.0 would replay the unhardened file — and rewriting a published tag would break the "tree bit-identical to ae633a87" property the v4.17.0 release decision rests on (house precedent: v3.15.2 abandoned → v3.15.3). No source change accompanies this fix; v4.17.1 carries the v4.17.0 tree plus the workflow.

## [4.17.0] - 2026-08-01

### Added

- **The README's repo-derived badges are now self-hosted SVGs, gated in CI** — `assets/badge-{license,python,tests,references,version}.svg`, `scripts/generate_repo_badges.py`, `scripts/badge_render.py`. Five hotlinked `img.shields.io` images became committed files, for the reason the MCP Toplist badge already was one: a remote badge URL is a third-party request fired on every README view, and it lets its host restate our claim with no commit in this repository. **Only repo-derived figures were converted**, and the line is deliberate — every one of these (licence, Python floor, collected test count, bibliography size, package version) is determined BY THIS REPOSITORY, so a committed copy can always be made true again from the working tree with no network access. That is why they are kept honest by a **blocking `--check` gate on every push and PR** rather than by a cron: drift is caught where it is introduced. **Two badges were deliberately NOT converted and must not be:** the CI status badge reports the LIVE result of the last run on main, so a committed copy would assert "passing" while main was broken — a static build-status badge is a false claim by construction, not merely a stale one — and it is GitHub-hosted, so it is not a third-party beacon in the first place; the OpenSSF Best Practices badge reflects an external body's live assessment that can be downgraded without any commit here, and `.bestpractices.json` separately justifies displaying THEIR badge image. The MCP Toplist badge sits between the two and stays committed because it carries an explicit "as of <month>" stamp, which keeps a stale copy a true statement about a point in time. **The conversion had to rewire the gate it would otherwise have silenced:** `check_doc_claims.py` enforced the version and test-count claims by regex over the shields.io URLs (`badge/version-(\d+\.\d+\.\d+)`, `badge/tests-(\d+)_passing`), so self-hosting alone would have left both patterns matching nothing while the gate still reported success. They now read the figure out of the committed SVG's own `<title>` and **fail closed** on a missing file or an unmatched title — the predecessor's `if badge and ...` passed silently the moment its subject disappeared. A new check also fails any reintroduced `img.shields.io` hotlink in the README, so reverting this is loud rather than quiet. Found by the new tests before shipping: `--` is illegal inside an XML comment, and the first cut described its own gate as `--check` and its source as `pytest --collect-only` in the provenance comment, leaving **all five badges unparseable**; the renderer now parses every badge it produces and refuses to return one that is not well-formed, so no future wording can reintroduce the class. The shared renderer was extracted from the MCP Toplist refresher first, as a separate behavior-preserving commit whose proof is that `assets/badge-mcp-toplist.svg` is byte-identical and its 51 tests pass unchanged. Suite grows 6348 → 6373.
- **MCP Toplist rank badge, self-hosted and refreshed on a cron** — `assets/badge-mcp-toplist.svg`, `scripts/refresh_mcp_toplist_badge.py`, `.github/workflows/mcp-toplist-badge.yml`. The badge records that Cortex ranks in the top 1.2% of MCP servers tracked by MCP Toplist (#964 of 81,919, read 2026-07-28). It is a **committed file, not a hotlinked remote image**: a remote badge URL is a third-party beacon fired on every README view, and it lets its host restate the claim at any time with no commit in this repository. The arriving PR (#241, closed) proposed exactly that. The cost of the static choice is that the badge cannot self-update — the date it carries is part of the claim and goes stale by INACTION, and inaction never opens a PR — so a monthly workflow regenerates it and proposes the diff. Monthly is deliberate: the badge stamps a month, so it is the least frequent cadence that keeps the date honest and the most frequent one that does not churn a PR proposing an identical file. Wording is **attributive throughout** (`RANKED in this tier by MCP Toplist`, never `is a top-1.2% server`), because upstream's own methodology page states the score "is a popularity and activity signal, not a quality assessment" and keeps ~25% of its weighting (organic reach, package downloads) undisclosed — the figure is attributable, not reproducible. Every generated SVG carries its own audit trail in a comment: source path, raw rank and field size, the percentile arithmetic, and the verify URL, so the next maintainer can re-derive the claim from the file alone. **Two extraction paths, fail-closed:** the structured export at `/data/leaderboard.json` is tried first but returns HTTP 503 (measured 2026-07-28: 3/3 attempts, 8–14s each under a browser UA, i.e. a server-side generation timeout, not UA gating or rate limiting), so its schema has never been observed and the parser accepts only a narrow set of documented candidate shapes under strict validation rather than guessing at one; the fallback is the server page's prose sentence `ranks #N of M servers tracked`, the ONLY construct on that page carrying both numbers (the `<title>`, og/twitter meta tags and all four JSON-LD blocks carry the rank without the total, so none can yield a percentile). Both paths feed one validator that refuses a non-numeric, zero, negative, or beyond-the-field figure — guarding the division in `percentile()` and the semantics of the claim — and a figure that fails validation is **never written**: the script exits non-zero, the badge keeps its last good value, and the run goes red. A fallback is never silent; the path that failed is reported even when a later one succeeds. No `pull_request` trigger, so a required check never depends on a third party's uptime; the 51 unit tests cover the logic with no network at all. Caught by those tests before shipping: a top-of-field rank renders the tier as `Top <0.1%`, whose unescaped `<` **made the badge invalid XML** — text and attributes are now XML-escaped, verified across the rank-1, mid-field and last-place boundaries. Note that PRs opened with the default `GITHUB_TOKEN` do not trigger workflows, so `main`'s required checks will not start on them; the workflow prefers an optional `BADGE_REFRESH_TOKEN` secret when present. Suite grows 6297 → 6373.
- **Pyright is now a zero-diagnostic blocking gate** (#197, final family of the maximal-strictness program). The 568-diagnostic per-rule ratchet backlog was burned to **zero** at `typeCheckingMode: "standard"` (pyright 1.1.410, measured 2026-07-28): no rule disabled, no floor raised; the single per-site suppression is the unpublished optional `cortex_beam_abstain` import whose `except ImportError` arm is the documented degraded mode. The ratchet machinery (`typecheck-baseline.json` + `scripts/check_pyright_ratchet.py`) is retired — CI fails on ANY diagnostic via pyright's own exit code, and the CI type-check env installs the `[otel]` extra so the exporter imports resolve. The burn-down was fixes, not annotations-to-match: a typed host contract for the eight `PgMemoryStore` mixins (`pg_store_host.PgStoreHost` + `MaterializedCursor`, whose honest `DictRow` typing surfaced ten unchecked `INSERT..RETURNING` sites, now `one()` with a real error), a cross-backend `StoreConnection` union for the 16 shared query modules (the psycopg-only annotation had switched checking off for every SQLite call path), and **SQLite store parity for eight methods callers already used unconditionally** — `acquire_interactive`/`acquire_batch`, `_execute`, `search_newer_neighbors`, `update_forgetting_pressure_accum`, `get_memories_by_tag`, `iter_memories_for_decay`, `find_co_accessed_pairs` — each of which previously raised `AttributeError` on the SQLite backend and was swallowed into silent degradation by broad stage boundaries. Latent bugs fixed en route, each with a regression test: the compat cursor lacked `executemany` (SQLite wiki page-sources writes crashed), `lastrowid` honesty (insert paths now raise on a broken row-id contract instead of masking it with a stale `type: ignore`), the pipeline installer accepted a success result carrying no cargo path (None flowed into the build argv), `update_style_ema(None, None)` returned `None` against a `dict` signature, `encode_session` died with a bare `TypeError` on a direction-less feature (now refuses loudly, naming it), `get_causal_chain` could return `reason=None`, and active forgetting sent a `None` timestamp into the store. `.bestpractices.json` flips `warnings_strict` to **Met**, citing the ruff select list, the pyright mode, and the measured zero. Suite grows 6275 → 6297.
- **ruff `PLC0415` (import-outside-top-level) and `S608` (string-built SQL) are now blocking lint gates** (#197, fourth rule family of the maximal-strictness program). All 520 production `PLC0415` findings (407 `mcp_server/`, 57 `benchmarks/`, 56 `scripts/`) were triaged one by one: **360 lazy imports moved to module top** — so the import graph is static and a broken module fails at boot, not mid-operation — and the 160 that remain each carry a per-site `# noqa: PLC0415 — <reason>` naming one of six sanctioned justifications: an optional dependency behind an extra, an internal module whose top-level closure hard-imports one (hoisting would break `[sqlite]`-only installs at import time), an ImportError-probe boundary where the except arm IS the degraded mode, an import cycle (partner named; the pre-existing #233 family), the hook latency boundary (per-event hook processes boot in ~0.05 s vs ~0.6 s for the registry closure, measured 2026-07-28 — hoisting the handler/store stack into a hook would multiply every hook event's cost), or a deferral the module itself documents. The hoist is behavior-preserving: the per-module import sweep matches the pre-change baseline exactly (515 modules, the same 6 pre-existing cycle failures), and warm import timings are unchanged. All 44 production `S608` sites carry a per-site `# noqa: S608 — <mechanism>` naming the exact reason the interpolation is safe (two-literal ternaries, generated placeholder lists, module-level `WHERE` literals, or allowlist-gated identifiers per `docs/ASSURANCE-CASE.md` §5), so any NEW string-built SQL fails CI until it states its mechanism. `tests_py/**` adds both rules to its written per-file ignore (function-level imports in tests are the fixture mechanism; SQL built in tests is fixture setup against a throwaway database).
- **ruff `PLR2004` (magic-value comparison) and `E501` (line-too-long) are now blocking lint gates** (#197, third rule family of the maximal-strictness program). All 420 production `PLR2004` findings (339 `mcp_server/`, 57 `benchmarks/`, 14 `scripts/`, 10 `video/`) were fixed with **zero `# noqa: PLR2004`**: every compared literal became a named constant carrying a `# source:` comment — a real citation where the module documents one (Frey & Morris 1997 / Kandel 2001 / Tse 2007 cascade thresholds, RFC 9110 status bands, FIPS 180-4 digest lengths, issue-quoted gates), a structural rationale for arities (split-parts, tuple lengths), and an explicit `pre-existing tuned value, extracted unchanged; provenance not recorded at introduction` where none is discoverable — never an invented source. `tests_py/**` carries a written per-file ignore (the compared literal in an assertion IS the expected value under test — the spec itself). All 470 `E501` findings (263 `mcp_server/`, 121 `tests_py/`, 48 `benchmarks/`, 37 `scripts/`, 1 `_pipeline`) were fixed by **rewrapping at the unchanged 88-column formatter limit** — string content kept byte-identical via implicit concatenation at existing whitespace (SQL and regex literals machine-verified byte-for-byte) — with exactly two per-site `# noqa: E501 — <reason>` for unsplittable absolute-path tokens; E501 has **no** tests ignore. Two drift risks were closed at the source: `handlers/consolidation/transfer.py` re-declared as bare literals the canonical constants of `core/two_stage_transfer.py` (whose own comment forbids redefinition) and now imports them; `benchmarks/beam/ablation.py`'s copies are named per-module without value drift.
- **ruff `BLE001` (blind-except) is now a blocking lint gate** (#197, second rule family of the maximal-strictness program). All 351 broad `except Exception` sites were triaged one by one, none blanket-ignored: (a) sites whose failure class is precisely known were **narrowed to typed excepts** — `json.loads` tag decoders to `ValueError`, lazy imports to `ImportError`, `subprocess` probes to `(OSError, SubprocessError)`, SQLite store guards to `sqlite3.Error`, PG connection/read guards to `psycopg.Error`, URL probes to `(OSError, ValueError, HTTPException)`, file I/O to `OSError` — so an unexpected programming error now **propagates instead of being absorbed** by a tolerant fallback; (b) genuine last-resort boundaries (degraded-mechanism wrappers, per-item batch isolation, hook/CLI entry points, diagnostic probes) stay broad and each carries a per-site `# noqa: BLE001 — <reason>` naming the signal it emits; (c) ~50 previously **silent** broad handlers now emit an observable signal — `silent_failure.note()` under 38 new stable component names (spreading-activation, wiki classifier user rules, candidate scans, memify reweight/derive, ingest tag lookups, prospective-trigger injection, source attribution, wiki pointer memories, AP-bridge/groomer config reads, …) or the hook log (`session_start` banner fetches, cached-graph lookups); (d) `mcp_client` connection failures re-raise with `from e`, preserving the causal chain. `tests_py/**` keeps a written per-file ignore (broad excepts in tests are deliberate teardown/optional-path handling). Every new signal is asserted by a test (54 added).
- **ruff `S110` (try-except-pass) is now a blocking lint gate** (#197, first rule family of the maximal-strictness program). `[tool.ruff.lint] select` is explicit in `pyproject.toml` (the former implicit defaults `E4`/`E7`/`E9`/`F`, plus `S110`), so CI fails on any newly swallowed exception in production code; `tests_py/**` carries a written per-file ignore (teardown/optional-path try-pass in tests is deliberate). All 68 production sites were triaged, none blanket-ignored: mechanism-degradation sites now report through `observability.silent_failure.note()` under stable component names (recall write-backs, RRF vector/FTS signals, sqlite vec-index maintenance, curation dedup, codebase-analyze edge/tag persistence, consolidation cascade/memify, doctor backend resolution, wiki reindex, LLM query reformulation), teardown/cleanup sites log at `DEBUG`, and sites whose failure class is precisely known were narrowed to typed excepts (hook cooldown caches, install-lock release, pre-migration sqlite guards, event-loop teardown). Every new signal is asserted by a test (57 added).

- **Doc-claim gate — `scripts/check_doc_claims.py`**: the counts the documentation advertises (standalone/with-integration tool counts, bibliography references, mechanisms, version, collected tests) are now checked against the repository on every push and pull request, not at release time. Each claim has one owner — `docs/mcp-tools.md` for the tool counts (itself pinned to the live registry by `tests_py/test_main.py::test_standalone_baseline_is_52_tools`), the bibliography for references and mechanisms, `pyproject.toml` for the version, a live `pytest --collect-only` for the test count — and every other file must agree. Release-history lines are exempt. A pattern that matches nothing fails rather than passing vacuously. Wired into the Lint job (static claims) and the 3.12 test job (test count).
- **Project governance and direction documents**: `GOVERNANCE.md` (decision model, roles and who holds them, continuity of access, DCO/CLA position), `docs/ROADMAP.md` (the twelve months to 2027-07, plus an explicit will-not-do section), and `docs/ASSURANCE-CASE.md` (security requirements, threat model, trust boundaries, secure-design principles mapped to code, CWE-by-CWE countermeasures, and what the case does not claim).
- **An explicit, mandatory testing policy** in `CONTRIBUTING.md`: behaviour-changing PRs ship tests in the same PR, a bug fix carries a regression test that fails on the pre-fix code, and every failure path asserts the signal it emits.
- **Document ingestion adapters — `ingest_document`** (#192): a new standalone MCP tool that ingests a **.docx** (OOXML zip, unpacked with the stdlib `zipfile`/`xml.etree` — no heavyweight dependency) or a **Confluence storage-format XHTML export** into the memory/wiki store. Both adapters parse into one typed model (`core/document_model.py`) via pure, zero-I/O parsers (`core/docx_parser.py`, `core/confluence_parser.py`) and a shared normalizer (`core/document_normalizer.py`) → the existing `wiki_write`/`remember` write path. Every produced wiki page and memory carries provenance (source path + content-hash version); re-ingesting the same document version is idempotent. Headings, paragraphs, and tables are extracted; **embedded images are skipped with an explicit notice** (no OCR); a malformed zip/XML fails **loudly and writes nothing** (no partial ingest). Filesystem/zip reading is isolated in `infrastructure/document_reader.py`; the tool composition root is `handlers/ingest_document.py`. This grows the standalone tool count 51 → 52. The shared parsing/normalization seam (`parse_confluence_storage` → `normalize_document` → write path) is what the live-Confluence REST connector (enterprise-backlog#28) will consume — that leg swaps only the byte source (REST fetch) and provenance (page URL + version).
- **MCP prompts capability** (#176): `prompts/list` + `prompts/get` publish three guided workflows composed from Cortex's real tool surface — `session_recall` (query_methodology → recall → unified_search → recall_hierarchical → memory_stats), `promote_memories` (episodic→semantic CLS: consolidate → memory_stats → curate_distill → remember), and `curate_wiki` (unified_search → curate_wiki → wiki_write → wiki_verify). Prompt step summaries are pulled from the same handler-schema map (`merged_schemas()`) that `tools/list` is built from, so a prompt's description of a tool cannot drift from the tool's own schema (the #98 drift class). `mcp_server/mcp_prompts.py`.
- **MCP tool profiles** (#177): a `full`/`lean` profile (`mcp_server/tool_profiles.py`) selected by `--profile` or `CORTEX_MCP_PROFILE`, enforced by `ToolProfileMiddleware`. `lean` advertises the 10-tool recall/onboarding surface (derived from `docs/mcp-tools.md` tiers + the common-session workflow); `full` keeps every tool. Per-profile `initialize.instructions`. Measured: `lean` cuts the per-session `initialize`+`tools/list` cost from ~29.9k to ~7.6k estimated tokens (74.6%), benchmark `benchmarks/mcp_profile_tokens.py`.

### Changed

- **Pyright now runs `standard` instead of `basic`** (#197 criterion 3), and the `_conn` annotation that made the raise look expensive is corrected. `SqliteMemoryStore` assigns `self._conn = PsycopgCompatConnection(raw)`, but 9 of its 10 mixins declared `_conn: sqlite3.Connection` (only `SqliteGroomingMixin` was right) — so every `self._conn.…` call in those mixins, and every handler reading `store._conn`, was type-checked against a class the store never holds. With all ten agreeing, `standard` and `basic` report the **identical 418 errors**: the raise costs nothing. Measured at the CI-pinned pyright 1.1.410 in a CI-equivalent environment (`reportMissingImports` lands at 1, matching `typecheck-baseline.json`, so nothing is Unknown-suppressed). `strict` is not adopted — it reports 10,231, ~9,300 of them the Unknown-type family, which is an annotation-coverage project rather than a config flip. The ratchet's blocking rules (`reportOptionalMemberAccess`, `reportOptionalSubscript`) stay at 0 and `typecheck-baseline.json` is untouched — no floor was raised to make the build pass. The corrected annotation immediately surfaced a live defect it had been masking: seven wiki handlers call `store._conn.cursor()`, which `PsycopgCompatConnection` does not implement, so the wiki pipeline is silently dead on the SQLite backend — filed as **#206**. Also fixes two `TYPE_CHECKING` imports in `tool_profile_middleware.py` that still pointed at FastMCP 2.x module paths (`fastmcp.prompts.prompt`, `fastmcp.tools.tool`); under the 3.x the project actually runs, those resolve to nothing and silently degraded `Prompt`/`Tool`/`ToolResult` to Unknown.
- **The doc-claim gate now covers the OpenSSF answers and the second test-count phrasing.** `.bestpractices.json` was not scanned, and its answers are transcribed verbatim into the OpenSSF Best Practices questionnaire — so a stale number there is published to the badge rather than merely sitting in the repository. Three of its test counts had drifted two corrections behind (5571 against a 5598-test suite), one of them inside a justification dated the day it was read. It joins `SCANNED_FILES`. The count pattern also read only the `N tests` wording, so the `N-test suite` phrasing went unchecked; `TEST_CLAIM` now matches both, with a test pinning that a count of *test files* is still not a claim about suite size.
- **Stale documentation claims corrected** (surfaced by the new doc-claim gate): the advertised tool count is 52 standalone / 55 with the optional upstream integrations (README said 50/53 in eight places, `CONTRIBUTING.md` said 43/46, `CLAUDE.md` said 51, the MCPB manifest said 49/52); the bibliography is 97 references behind 36 mechanisms (`CONTRIBUTING.md` said 72 and 23, the manifest the same); the advertised test count is 5598 and the version badge is 4.16.0. `CONTRIBUTING.md` documented a `mypy --strict src/cortex/` gate and a `black` formatter the project has never run — the real gates are ruff (pinned 0.15.20) and the pyright per-rule ratchet — and attributed a `pre-tool-secret-shield` file gate to Cortex that belongs to the maintainer's local agent tooling; in-repo the defence is `mcp_server/shared/redaction.py`. Prerequisites no longer claim PostgreSQL is required (SQLite is the default store). `docs/api-reference.md` still documented `get_methodology_graph` and `open_visualization`, extracted to cortex-viz in v3.21.0 — both sections are replaced by a pointer, and the same stale references are corrected in the `/methodology` command, `docs/mcp-tools.md`, and two MCP tool descriptions (`get_rules`, `explore_features`) that told the model about a tool this server no longer registers. The README's citation section pointed at a non-existent `docs/science.md`.
- **Pyright type-debt burned back below the 568 baseline** (#188): the `MemoryStore` factory now types its `__new__` / `get_shared_store()` / `_construct_store()` results as the real `PgMemoryStore | SqliteMemoryStore` union it actually builds, instead of the empty factory shell pyright previously saw. That shell suppressed attribute resolution across 55+ handlers (every `store.get_memory(...)` read as "attribute for class MemoryStore"); annotating the real return type drops the tree-wide pyright total from 638 to 422 (`reportAttributeAccessIssue` 387→192, `reportReturnType` 52→18, `reportAssignmentType` 26→1). Truthful typing also unmasked latent argument/call errors previously hidden behind the shell — these stay visible in the ratchet's tracked (non-blocking) counters for iterative burn-down. No runtime behaviour change: the `MemoryStore` name is a `TYPE_CHECKING`-only union alias; the runtime factory class is byte-identical. Blocking-tier fix: `wiki_emerge`'s cold-start `COUNT(*)` read now guards the (SQL-unreachable) `fetchone() is None` case the truthful type exposed.
- **The default MCP tool profile is `full`** (behaviour preserved; H4 note). This diverges from #177 criterion 2's "default to the common-session profile": shrinking the default advertised surface is a breaking change (a client that called a now-hidden tool would break), so — mirroring `automatised-pipeline`'s `ToolProfile` reasoning and this wave's explicit decision — `full` stays the default and `lean` is opt-in. Existing sessions are unchanged; the middleware is a pass-through under `full`.


- Development-tooling and CI dependency bumps merged ahead of this tag: `pyright` 1.1.410 -> 1.1.411 (#327), `dill` 0.3.7 -> 0.4.1 (#326), `ruff` 0.15.20 -> 0.16.0 (#321), and a Dependabot configuration change ignoring `caio` >= 0.10 with the pip resync step documented (#329). None touches the retrieval, write-gate, or consolidation paths.

### Removed

- **Two modules whose call site was never built** (#196, criterion 1). `infrastructure/git_diff.py` (with its private siblings `git_diff_exec.py` and `git_diff_format.py`, whose only importer it was): its one caller, `server/http_file_diff.py`, was deleted deliberately in the Phase 6 visualization strip, and the behaviour now lives in the **cortex-viz** MCP — `cortex_viz/server/git_diff_engine.py`, shipped in v2.7.1, routed at `/api/file-diff`, with its own test suite; that module exists precisely because the copies descended from this one had diverged and were losing patches on merge commits. The one proposal to build an in-Cortex caller (`core/git_diff_to_symbols.py`) was retracted in the corrected gap analysis, since `automatised-pipeline`'s `detect_changes` already does it and `hooks/pipeline_impact_bump.py` already calls it. `shared/memory_types.py`: 9 Pydantic models with zero references anywhere, whose docstring claimed to define "the schema for SQLite storage and handler I/O" while the real contract is `dict[str, Any]` normalised by `sqlite_store` and validated per-tool by `validation/schemas.py` — the same species as the 13 scaffolding models removed earlier, verified by the same method.
- **`core/context_assembly/active_retrieval.py` (issue #201, the second of #196's flagged zero-importer pair alongside `decomposer.py`).** `grep -rn "context_assembly.active_retrieval"` across `mcp_server/`, `tests_py/`, and `benchmarks/` (excluding the module's own directory) returned nothing — no production handler, no benchmark harness (`benchmarks/beam/run_benchmark.py` calls `pg_recall.assemble_context`, which never reaches this module), and no test beyond the module's own two test files. `decomposer.py`'s companion half of #201 was already resolved on `main` before this issue could be picked up: `condensers.condense_assembled_context` (now `condense_stage.py` post-#228 split) calls `decomposer.assemble_prompt` from `pg_recall.assemble_context`'s over-budget path, itself exercised by the BEAM benchmark harness — a real, non-test caller — so `decomposer.py` and its sole consumer `warning.py` both stay. `active_retrieval.py` had no equivalent: checked git history (added whole in the 3.18.4 release commit `5eba011`, touched twice since only for lint-family constant/exception-handling sweeps, never gained a caller) and all 12 unmerged remote branches (`git grep` for `active_retrieval|ActiveRetriever|KeywordExtractor|LLMReformulator` across each `origin/main..<branch>` diff — zero hits) for a removed or pending caller; found none. Wiring it would be new retrieval-affecting behaviour (MIRIX-style query reformulation ahead of the WRRF pipeline) needing its own benchmark validation, not a mechanical fix — out of scope for a dead-code removal. Deleted with its direct test file (`tests_py/core/context_assembly/test_active_retrieval.py`, 18 tests) and the two S110-sweep regression tests in `tests_py/core/test_s110_sweep_core.py::TestActiveRetrievalReformulate` that existed only to cover its `except`-logging path (#197 family 1) — both entirely about behaviour that no longer exists. `docs/module-inventory.md`'s `core/context_assembly/` count corrected 15 → 14 (`core/` 230 → 229); `docs/papers/research-post-context-assembly.md` §3.4 and its `docs/arxiv-context-assembly/main.tex` mirror (§ Active Retrieval) reworded from "the interface is defined and wired" to the accurate "never composed into the WRRF pipeline or the BEAM harness — removed as dead code", and both papers' Appendix-C module tables drop the `active_retrieval.py` row. Suite: 6938 passed, 5 skipped, 121 subtests passed (pre-change) → 6918 passed, 5 skipped, 121 subtests passed (post-change), the 20-test delta being exactly the deleted tests; zero tests modified.

### Fixed

- **The two background-reanalyze spawns resolved the interpreter by PATH name before `sys.executable`, hitting the Windows Store stub** (#315). `mcp_server/shared/platform.py::python_executable()` exists specifically to avoid this (its docstring: `shutil.which("python3")`/`("python")` resolve to the Microsoft Store stub on Windows, which exits without running anything), and `doctor_mcp.py` already used it — but `post_commit_reindex.py::_spawn_reanalyze` and two call sites in `session_start.py` (`_spawn_consolidate_cycle`, `_maybe_background_reanalyze`) still used `shutil.which("python3") or shutil.which("python") or sys.executable`, falling back to `sys.executable` only when PATH resolution failed outright — not the actual failure mode, which is PATH resolution *succeeding* against the broken stub. All three call sites now use `python_executable()`, matching `doctor_mcp.py`'s existing pattern. Both spawn helpers are detached background processes (`ingest_codebase_background`, `consolidate_background`) with no prior direct test coverage of their command construction — `tests_py/hooks/test_post_commit_reindex.py` and `tests_py/hooks/test_session_start.py` gain tests asserting the exact resolution order (a PATH entry that would resolve to a stub interpreter is proven to lose, via a mocked `shutil.which` returning a distinguishable fake path), the full spawned command (interpreter, launcher path, module args), the `subprocess.Popen` kwargs (`stdin`/`stdout`/`stderr`/`start_new_session`), the exact (case-sensitive) log path, the `CLAUDE_PLUGIN_ROOT`-unset fallback to the repo root, and the non-fatal failure/success log messages — a scoped mutation run (`scripts/mutation_check.sh`) against the three modified functions reports 0 surviving mutants.
- **`codebase_analyze` crashed with an uncaught `tree_sitter_language_pack.DownloadError` when a grammar could not be fetched** (main-red, CI run 30592244731, 2026-07-31, `Test (Python 3.10)`: `tests_py/benchmarks/test_codebase_alteration.py` (5 tests) and `tests_py/core/test_ast_extractors.py::test_decorated_function`). `tree-sitter-language-pack` is a declared dependency, but it resolves each grammar's shared library **lazily over the network at `get_parser()` call time**, not at install time — confirmed by measurement: an already-cached language returns in <50ms with no network attempt, an uncached one takes a real round trip against `https://github.com/xberg-io/tree-sitter-language-pack/releases`. `mcp_server/core/ast_parser.py::_get_extractor_and_tree` already treated a **missing** pack (`ImportError`) as a handled degraded mode, but had no handling for a pack that imports fine and then fails to **fetch** a grammar — an offline install, an air-gapped environment, a proxy, or an upstream outage reached `get_parser(language).parse(content)` (line 99) uncaught, so `codebase_analyze` raised a third-party exception type to its caller instead of degrading. Same defect class this repo has already been bitten by twice (the FlashRank silent-absence incident; the MCP stdio response-loss above): a degraded path existed and did not cover the failure that actually happens. Fixed by catching `DownloadError` specifically (not widened to the pack's broader `Error` base — only `DownloadError` is evidenced) around the `get_parser().parse()` call, returning the same `None` degraded-mode signal `parse_file_ast` already reads to select the regex fallback, and logging one actionable warning naming the language and the reason on every occurrence (not suppressed after the first — this runs once per file, not once per process). Regression tests force the failure deterministically (`monkeypatch.setattr` on the pack's own `get_parser`, matching the file's existing `ImportError`-probe convention) rather than by disabling real network: `tests_py/core/test_ast_parser_language_contract.py` gains `test_download_error_falls_back_instead_of_raising`, `test_download_error_logs_language_and_reason` (asserts the log emission itself, not merely the absence of a crash), and `test_download_error_degrades_through_parse_file_ast` (the public entry point `codebase_analyze` calls) — all three verified to fail against the pre-fix code. Made the test suite hermetic rather than papering over the flake: `.github/workflows/ci.yml`'s `test` and `test-sqlite` jobs (the two that install the `codebase` extra) gain a `Resolve tree-sitter cache directory` + `Cache tree-sitter grammars` + `Prefetch tree-sitter grammars` step trio — same cache-then-retry-with-backoff shape as the existing HF-embedding/FlashRank steps, for the same reason: fetch every language in `AST_SUPPORTED` (read from the module, not hand-copied, so the step cannot drift from what `ast_parser.py` actually uses) once, with retries, before `pytest` starts, so the suite's existing direct `get_parser(...)` calls in `test_ast_extractors.py`/`test_ast_parser_language_contract.py` never touch the network mid-run. No other unguarded `get_parser`/`get_language` call site exists in `mcp_server/` (swept repo-wide; `ast_parser.py` line 99 was the only production call).
- **"Docker Smoke" intermittently reported no `tools/list` response with no exception and no JSON-RPC error frame** — reproduced on `main` (CI run 30504042295: attempt 1 failed, attempt 2 succeeded, same commit `56f2f4f`, no code change), on PR #254 and PR #266. Root cause is upstream: `mcp` 1.29.0's `BaseSession._receive_loop` (`mcp/shared/session.py`) closes the write stream unconditionally the instant stdin reaches EOF, even when a request dispatched from an earlier line in the same batch (`tools/list` after `initialize`) is still running in its own task and has not called `respond()` yet — `mcp.server.lowlevel.server.Server._handle_request` catches the resulting `ClosedResourceError` and logs it via `logger.debug()` on a logger with zero handlers by default, so the drop is completely silent. All three JSON-RPC lines are always fully read (measured `parsed_count == 3` on every trial, pass and fail alike) — nothing is ever left unread; only the already-computed response is lost. `fastmcp` 3.4.5's `LowLevelServer.run` override removes the base SDK's own `finally: tg.cancel_scope.cancel()` mitigation with nothing in its place, so Cortex's stdio entry point inherited the hazard unmitigated. Fixed at Cortex's composition root: `mcp_server/infrastructure/stdio_transport.py` interposes a write-stream proxy that no-ops the SDK's premature `aclose()` and closes the real stream only after the low-level server's `run()` call has returned — which, by anyio task-group join semantics, is only once every dispatched handler has had its own chance to respond. `mcp_server/__main__.py::main()` now drives stdio through this wrapper instead of `mcp.run(transport="stdio")` directly. Regression test at the SDK boundary (`tests_py/infrastructure/test_stdio_transport.py`): one test reproduces the drop against the bare upstream call directly (a permanent characterization of the upstream defect), a second drives the identical race through the fix and asserts the response survives — verified to fail against the pre-fix code (bypassing the guard reproduces the exact original symptom: `initialize` answered, `tools/call` silently missing). A scoped mutation run (`scripts/mutation_check.sh`) against the new module found 9 further survivors and 22 uncovered mutants; hardened in `tests_py/infrastructure/test_stdio_transport_wiring.py` (the `stateless` parameter's actual MCP-lifecycle effect, and the outer `run_stdio_drained` wrapper's banner/transport-context-var/log-message wiring) and `_stdio_transport_helpers.py` (shared fixtures, split out to keep both files under the 500-line cap) — final scoped mutation score: 42/43 killed, 1 documented-equivalent (`typing.cast`'s type argument is never read at runtime, same argument as `json_native.py`'s below). `scripts/docker_smoke.sh` gains a second, independent hardening: its `timeout`/`gtimeout` wrapper was itself measured (2026-07-30) not to reliably stop a genuinely hung container (SIGTERM to the `docker run` CLIENT process does not reliably reach the CONTAINER) — the container could outlive its supposed 60s bound indefinitely. A `--cidfile`-based watchdog now `docker kill`s the actual container ID after the same 60s budget, verified against a deliberately hanging test image (fails in exactly 60s, no leaked container) and a deliberately broken/exiting one (fails immediately) — both directions proven stable across repeated runs, on both the `timeout`-available and no-timeout-binary code paths. Boy-scout: `MIN_TOOL_COUNT`'s default and source comment had drifted to 49 (citing a test name, `test_standalone_baseline_is_49_tools`, that no longer exists) against the true current baseline of 52 (`tests_py/test_main.py::test_standalone_baseline_is_52_tools`) — the gate's floor was silently weaker than it should have been by three tools' worth of regression headroom; corrected in the same change. Review found one more divergence before merge: `run_stdio_drained`'s `show_banner` defaulted to a hardcoded `True` rather than resolving `fastmcp.settings.show_server_banner` the way the composition root's replaced call (`mcp.run(transport="stdio")`, via `TransportMixin.run_async`) does — a user who disabled the banner via `FASTMCP_SHOW_SERVER_BANNER=false` got it printed on stderr on every stdio launch regardless. Fixed by defaulting `show_banner` to `None` and resolving the setting at that point, exactly where `run_async` does, so an explicit argument still overrides it; pinned in both directions by `tests_py/infrastructure/test_stdio_transport_wiring.py`. Review found a second, size-only finding: the banner fix's docstring/citation additions pushed `run_stdio_drained` to 54 lines, over both the hard `§4.2` 50-line cap and this repo's own 40-line/method `CLAUDE.md` convention. Behavior-preserving refactor (Fowler 2018 Ch. 6, Extract Function): the banner resolution and its sourced citation move into a new `_resolve_show_banner()` helper (27 lines); the same pattern is applied to `_run_low_level_drained`, which the same measurement pass found already at 57 lines, by extracting the `mcp._mcp_server.run()` call and its `cast()`-equivalence citation into `_run_mcp_with_guarded_stream()` (37 lines) — both public functions land at 39 lines, no test added or modified, same 14/14 targeted + 732/732 (5 skipped) infrastructure-suite pass counts before and after. While relocating the citation, the two upstream line-number references it carried (`fastmcp/server/mixins/transport.py` `L56-57`/`L184-186`) were verified against the actually-installed `fastmcp==3.4.5` in `.venv` and found to be a consistent −32-line offset from the real `run_async`/`run_stdio_async` locations (`L88-89`/`L216-218`); corrected in place rather than carried forward unchecked.

- **`condensers.py`'s 123 pre-existing surviving mutants outside #196, closed** (#228). A scoped mutmut run left every non-#196 condenser with survivors no test could distinguish: `condense_code_block` (29), `condense_assistant_message` (28), `condense_memory_content` (24), `condense_timeline_event` (15), `condense_user_message` (11), `condense_entity_triples` (9), plus the fence-splitting helpers (7). The file was also 391 lines (over the 300-line §4.1 cap) with two functions over the 40-line §4.2 cap, so the behaviour-preserving split came first (`docs/audits/condensers-mutation-run-2026-07-30.md`): one file per condenser family — `condense_text.py`, `condense_code.py`, `condense_structured.py`, `condense_dispatch.py`, `condense_stage.py` — behind an unchanged `condensers.py` re-export facade, verified against the pre-existing 36-test suite (plus the #196 `pg_recall` wiring tests) passing unmodified before a single new test was added. Four new test files add exact-equality contract tests (boundary pairs, accounting ladders, literal rosters, exact routing) mirroring the split. Re-scoped mutation run: 383 mutants (383, not 352 — a few new comparison sites from the extraction), 377 killed, 6 documented-equivalent survivors (three `<=`→`<` boundary ties that fall through to an identical no-op truncation, two loop-index `<`→`<=` ties provably unreachable given how the two indices are built, and the #196 priority `3`→`4` tie re-confirmed after the split). One genuine dead-code branch surfaced by the run (`condense_assistant_message`'s trailing code-only fallback, which every mutant of survived) is deleted per §9/§12.1 rather than kept as speculative future-proofing, with the unreachability proof moved to the use site and pinned by two tests; a stale "late import" docstring claim about `assemble_prompt` (the import was already module-scope) is corrected in the same pass (§14).
- **`sqlite_sql_translate.py`'s 20 surviving mutants, closed** (#265). This module (`_translate_sql`/`_returning_was_stripped`, split out of `sqlite_compat.py` by #260) left 20 mutants surviving a scoped mutmut run — every one the same shape: a mutant dropping (or re-spelling the case of) the `flags=re.IGNORECASE` argument on one of the module's `re.sub`/`re.search` calls. Every existing case-insensitivity fixture supplies an input whose case already matches the pattern's own literal spelling, so the flag's presence was never observable. A rescoped run on this tree measured 19 of the 20 named ids still surviving (`mutmut_136` had flipped to killed between runs — non-deterministic mutant/worker ordering, not a real fix, folded back into the equivalent set below by direct regex comparison). Six are real gaps, closed with `tests_py/infrastructure/test_sqlite_sql_translate_265.py` supplying the opposite-case input for each: lowercase `DEFAULT now()`, an uppercase `&&`-overlap column, `XMAX`/`as` case variants on the xmax-drop rule, a lowercase `RETURNING` strip inside `_translate_sql` distinct from the one `_returning_was_stripped` already covered, an uppercase `ARRAY_LENGTH`, and lowercase `_returning_was_stripped` input under a monkeypatched `_SUPPORTS_RETURNING` — 6 new tests, all failing on pre-fix code. The remaining 14 are **documented equivalent mutants**: the mutation only re-spells the pattern's own literal case (`SERIAL`→`serial`, char classes `[a-z_]`↔`[A-Z_]`, etc.) while `re.IGNORECASE` stays in place, which Python's `re` semantics make provably irrelevant to the match — confirmed empirically with a differential harness (uppercase/lowercase/mixed-case probes against the original and mutated pattern, identical match results in every case) rather than asserted by inspection alone. Re-running the reproduction after the fix: 6 killed, 14 equivalent, 0 unaccounted-for survivors.
- **`mcp-toplist-badge.yml`'s monthly refresh can now actually open its PR** (#273). A real `workflow_dispatch` run (triggered while dispatch-verifying #246) reached `Open refresh PR` and failed there: `GitHub Actions is not permitted to create or approve pull requests`. The repo had **"Allow GitHub Actions to create and approve pull requests"** unchecked at Settings → Actions → General, which blocks PR *creation* itself — a stronger failure than the one the workflow's own comment anticipated ("GitHub deliberately does not trigger workflows on `GITHUB_TOKEN`-authored PRs", which only explains why such a PR's checks don't start, not why it would fail to be created at all). Fixed at the repo-policy layer (`gh api -X PUT repos/cdeust/Cortex/actions/permissions/workflow -F can_approve_pull_request_reviews=true`), which is where the root cause lives — not in the workflow, which already had the correct `secrets.BADGE_REFRESH_TOKEN || secrets.GITHUB_TOKEN` fallback and needed no logic change. The workflow's comment now documents both distinct failure modes and the fix, so a future repo transfer or org policy reset that reintroduces this is diagnosable from the file alone. A stray `chore/mcp-toplist-badge-refresh` branch pushed-then-abandoned by the earlier failing run had already been deleted (confirmed absent by this fix); the verification run for this fix leaves no stray branch either — its outcome is quoted in PR #273's description.
- **`sqlite_compat.py` relied on sqlite3's *implicit* default `datetime` adapter, deprecated as of Python 3.12** (#260), firing on 3 tests (`test_consolidate.py::test_with_memories`, `::test_protected_memories_skip_compression`, `test_memory_lifecycle.py::test_store_consolidate_recall`). Root cause: `cascade.py::_update_stage_entered` binds a raw `datetime.datetime` object as a SQL parameter instead of an ISO string — confirmed the **sole** such call site in this codebase by instrumenting all three `execute`/`executemany` paths in `sqlite_compat.py` and running the full suite against it. Fix: an explicit `sqlite3.register_adapter(datetime, _adapt_datetime_iso)` (the sanctioned Python-docs recipe the deprecation warning itself points to), writing the same "T"-separated `.isoformat()` spelling every other datetime write path here already produces (`sqlite_store._now_iso()`, etc.) — one canonical wire format instead of two. Old rows on disk (the deprecated adapter's space-separated spelling) keep reading correctly: `datetime.fromisoformat()` — the read path every consumer here uses — parses both spellings to an identical value (verified empirically and pinned by a test), so **no migration is required**. A `pyproject.toml` `filterwarnings` entry turns this specific DeprecationWarning into a hard failure going forward — a regression tripwire, not a silence. Boy-scout: `sqlite_compat.py` was already 335 lines — over this repo's 300-line file cap — before this change touched it; split the pure SQL-dialect translation logic (`_translate_sql`/`_returning_was_stripped`/`_SUPPORTS_RETURNING`) into a new `sqlite_sql_translate.py` module (behaviour-preserving, byte-identical logic), retargeting the two existing tests that monkeypatched `_SUPPORTS_RETURNING` to the module that actually defines it. Scoped mutation testing (mutmut) against the touched `sqlite_compat.py` surfaced 13 pre-existing gaps in `_CompatCursor`/`_CompatExecutingCursor`/`PsycopgCompatConnection` field wiring (not the datetime fix itself) — added targeted tests for all of them; one mutant (`executemany`'s `self.lastrowid = None`) is a documented equivalent (`sqlite3.Cursor.lastrowid` is only meaningful after a single-row `execute()` INSERT, so it is always `None` after `executemany()` regardless of which literal is written). A separate mutation gap in `_translate_sql` itself (20 survivors, verbatim regex-translation code moved unchanged from `sqlite_compat.py`, same tests before/after) predates this change and is filed as #265 rather than folded in, per §14.3.
- **The typecheck gate's zero-diagnostic verdict was a property of the pip resolver, not of the source** (#249). `mcp_server/core/ast_parser.py:88` called `tree_sitter_language_pack.get_parser(language)` with a plain `str`; `get_parser`'s declared parameter type differs across the package's own releases — a `SupportedLanguage` `Literal` union in 1.6.2 (what `uv.lock` resolved when this was filed) versus a plain `str` in 1.13.5 (what both `uv.lock` and a fresh pip resolution give today) — so the same call was a pyright error under one and silently clean under the other, and a `set[str]` `in` test narrowed nothing either way. `AST_SUPPORTED` is now a `Literal` union (`_SupportedLanguage`) narrowed via a `TypeGuard` (`_is_ast_supported`) rather than a bare `set[str]`; reproduced against both a live 1.6.2 install and the current 1.13.5 one (`pyright mcp_server/`: 1 error → 0 under 1.13.5; the 1.6.2 stub's own `SupportedLanguage` omits `"csharp"` outright — a pre-existing grammar-availability gap in that release, not a narrowing defect, and unreachable under any version this repo's floor resolves to today). The typecheck CI job now quotes the resolved `tree-sitter-language-pack` version in its log, since that resolution is now load-bearing evidence for the verdict, not incidental (the job's environment reproducibility and its `uv.lock`-drift guard were already closed by #244's hash-pinned `requirements/ci-typecheck.txt`). Boy-scout pass on the touched file: the flat `calls` list every per-language extractor computed via `extract_calls_generic` and `parse_file_ast` immediately discarded (superseded by `calls_per_function`, never itself consumed) is removed rather than given a test; Swift and Rust parsing had zero test coverage through `parse_file_ast` (`_extract_swift`/`_extract_rust` were unreachable from any existing test — the Go equivalent bypassed its own wrapper by calling `extract_go_definitions` directly) and now do, alongside coverage gaps in `is_available`, `_node_text`, `_extract_module_doc`'s docstring/comment branches, `content_hash` length, and `calls_per_function`'s populated content. Suite grows 6526 → 6549.
- **`ast_parser`'s per-language extractors carried a dead return value, and two grammars had zero test coverage through their real call path** (boy-scout follow-on from #249; the resolver-dependent typecheck defect #249 itself named was independently closed by #253/#251's `_is_ast_language`/`SupportedLanguage`-derived-`AST_SUPPORTED` fix, already on `main`). Every per-language extractor (`_extract_python`/`_extract_js`/`_extract_go`/`_extract_swift`/`_extract_rust`, plus the JVM/C-family/scripting extractors `ast_extractor_registry.build_extra_extractors` composes) computed a flat `calls` list via `extract_calls_generic` and returned it as a 3rd tuple element that `parse_file_ast` immediately discarded — superseded by `calls_per_function`, the value actually consumed downstream. Removed; `Extractor` is now a 2-tuple `(imports, definitions)`. That element was the entire production call graph of `extract_calls_generic` (`mcp_server/core/ast_extractors.py`) — with it gone, the function had no caller left but its own direct unit test, so `extract_calls_generic` itself, its `TestCallExtraction` unit test, and the stale "also provides the generic call-site extractor used by all languages" line in the module docstring are removed/corrected too. Swift and Rust parsing had never been exercised through `parse_file_ast` by any existing test (the Go equivalent bypassed its own wrapper by calling `extract_go_definitions` directly) — added `TestParseFileGo`/`TestParseFileSwift`/`TestParseFileRust`. Smaller gaps closed alongside: both branches of `is_available()`, the docstring/comment-extraction branches of `_node_text`/`_extract_module_doc` (via fake-`Node` unit tests), `content_hash`'s length invariant, `calls_per_function`'s populated content, and malformed-UTF-8 decode robustness (`errors="replace"`). Net +20 tests relative to `main` (23 added, 3 removed: 2 with `extract_calls_generic`'s own unit test, plus a rebase-time removal below of a since-obsoleted mutation-guard test whose call site this same change deletes); no absolute total is stated here per #293/#294 — `assets/badge-tests.svg` is the one artifact that still states one, precisely because a CHANGELOG entry hand-carrying a total goes stale the moment any other PR merges first.
- **A `created_at` that states a timezone was stored as the wrong instant** (#252). `normalize_date_to_iso` had no timezone policy on any of its paths, so three defects stacked: (1) the "already ISO" guard was the substring test `"T" in raw`, and every US zone abbreviation contains a T — `8 May 2023 13:56 EST` was returned unparsed; (2) the built-in fast path matches the date at the START of the string and discards the rest, so `8 May 2023 13:56 +02:00` became midnight, dropping both the time and the offset; (3) on the dateutil path an abbreviation it cannot resolve is dropped with a warning nobody sees, leaving a naive datetime that PostgreSQL's `timestamptz` cast and `compute_recency_boost` both read as UTC. The instant was up to a day off and nothing was emitted. A stated zone is now honoured or the value is refused: `mcp_server/core/temporal_timezones.py` supplies dateutil a `tzinfos` resolver over the **RFC 5322 §4.3 obs-zone table** (the normative answer to "which EST?" — cross-checked against CPython's `email._parseaddr._timezones`), and any abbreviation outside it is refused with a warning naming the input, the abbreviation and the fix, rather than defaulted. Parsing no longer depends on the host's local zone name, and no `warnings.catch_warnings()` — process-global and not thread-safe — is taken on a store write path. `normalize_date_to_iso` moves out of `core/temporal.py` into `core/temporal_normalize.py`: storage normalization must not lose precision, retrieval scoring may, and they are now separate modules (both stores import from the new path). The refusal also covers the degraded path — a string that states a zone is never salvaged to a naive date, whatever made the parse fail.
- **`python-dateutil` is now a declared dependency** (#252). `normalize_date_to_iso` has always parsed free-form dates with a time of day through it — the LoCoMo shape `1:56 pm on 8 May, 2023` its own docstring cites — but it was never declared and arrived only by transitive luck. It was absent from every `requirements/ci-*.txt`, so **every CI test job ran with that parser missing**: the fallback was dead code in CI, and any install resolving without it kept dates it could not read. Declared, locked and hash-pinned into the 9 exported requirement sets, so the write path behaves identically on every install and both backends.
- **Both stores skipped the normalization entirely for the dates that needed it most** (#252, the same substring defect one layer up). `PgMemoryStore._build_insert_params` and `SqliteMemoryStore._insert_memory_rows` each guarded the call with `"T" not in raw_created` as a cheap "is it already ISO?" test — so `8 May 2023 13:56 EST` (and every `PST`/`CST`/`MST` string) went to the database untouched, whichever way `normalize_date_to_iso` behaved. The guard is gone from both: deciding what is already ISO belongs to the function that owns it, which returns a real ISO datetime unchanged. Asserted on the stored row, not just on the parser, and asserted equal across the two backends.
- **Plugin installs bootstrapped a dependency set this repo no longer resolves** (found while wiring the above). `scripts/launcher_deps.py` carries the pin table the launcher pip-installs before the plugin's own dependencies exist, every row commented `# source: uv.lock` — and nothing verified it. 7 of the 9 rows had drifted: `fastmcp 3.2.4` (locked 3.4.5), `pydantic 2.13.3` (2.13.4), `pydantic-settings 2.14.0` (2.14.2), `psycopg 3.3.3` (3.3.4), `psycopg_pool 3.3.0` (3.3.1), `pgvector 0.4.2` (0.5.0 — the version whose psycopg loader change `pg_store._vector_to_bytes` is written for), `sentence-transformers 5.4.1` (5.6.1), plus a `numpy` marker split the two-branch constant no longer covered (2.4.4 is not in the lock at all). Realigned, and a test now asserts every pin is a version `uv.lock` records, with a negative control. Two prose copies of the same numbers — `docs/deployment-scenarios.md`'s container versions and a `pyproject.toml` comment — now point at the lock and its hashed exports instead of restating them.
- **The pyright gate no longer depends on which installer you used, and the pin it depends on no longer admits a version that crashes** (#253, #249, #251). The zero-diagnostic gate read a different `tree-sitter-language-pack` in each environment: CI installed the hash-pinned export of `uv.lock` while the documented developer install resolved `pyproject.toml`'s `>=0.24.0,<1.14` range, and the two landed seven minor versions apart — one error in one environment, zero in the other, on the same commit. Chasing the divergence to its source found a live defect underneath it. **The pin now admits only the versions where the call chain actually works** (`>=1.12.5,<1.14`): one probe per published wheel plus one pyright run each shows `<=1.6.2` exports a 179-name `SupportedLanguage` literal *without* `csharp`, 1.6.3's macOS wheel ships no package, no 1.7.x was ever published, 1.8.0 exports no such symbol — and **1.9.0 through 1.12.2 return a `builtins.Parser` whose `parse(source: str)` rejects bytes**, so `get_parser("python").parse(b"...")` raises `TypeError: 'bytes' object is not an instance of 'str'` uncaught and `codebase_analyze` dies. The old comment on this pin described exactly that window ("1.7.0+ ... AttributeError on instances of `builtins.Parser`") while the pin it annotated said `<1.14` and admitted it. `tests_py/core/test_ast_parser_language_contract.py` now parses with every declared grammar, so the crash cannot come back silently. **The call site passes the literal type instead of `str`**: `_EXTRACTORS` is keyed by the pack's `SupportedLanguage`, so the checker verifies each grammar name against the pack the environment actually resolved, and `AST_SUPPORTED` is now *derived* from that table rather than restated beside it — which deleted an unreachable fallback arm (the two lists could not disagree, so `extractor is None` never happened) and makes `_EXTRACTORS[language]` total after the `TypeGuard` narrows. **And both sides install from the lock**: `CONTRIBUTING.md` documents the `uv sync` that reproduces CI's type-check environment, `tests_py/scripts/test_typecheck_env_parity.py` asserts its extras/groups equal the `ci-typecheck.txt` / `typecheck-tool.txt` entries of `scripts/pip_constraint_sets.py`, the dev-setup install stops resolving from the pyproject ranges, and the Type Check job now prints the three package versions its verdict depends on. `pyright mcp_server/` reports `0 errors, 0 warnings, 0 informations` at 1.12.5, 1.13.0, 1.13.5 (locked) and 1.13.6 (newest admitted); the pre-change tree reproduces the reported diagnostic against the 1.6.2 type surface. Four pre-existing shellcheck findings in the touched `ci.yml` (`SC2015` ×3, `SC2034`) are fixed in the same change.
- **`docker/Dockerfile` could not build at all**: it copied `/usr/local/lib/python3.12/site-packages` from the builder against a `python:3.14` base — a path absent from both stages since the base image moved off 3.12. Invisible because **no CI job built this image**; it now installs into a version-free venv (the rule the root Dockerfile already documents, from the incident where a literal `python3.13` path broke on every base bump). Both `docker/Dockerfile` and `.devcontainer/Dockerfile` gain build jobs in `ci.yml`, so the next such breakage is visible.
- **`scripts/setup.sh` reported success over any install failure**: the dependency install ended in `2>/dev/null`, which is where a resolution failure, a hash mismatch and a network error all appear, and the script printed "Python packages installed" regardless. Its exit status is now checked. Its hand-written package list — a duplicate of `pyproject.toml` — had already drifted from it, asking for `sentence-transformers>=2.2.0` against a real floor of `>=3.0.0`, and is replaced by the generated hashed file.
- **`.gitattributes` marks `fuzz/corpus/**` as binary**: end-of-line normalisation would have rewritten the CRLF corpus seed to LF on checkout, silently deleting the case that seed exists to cover.
- **`.bestpractices.json` was committed carrying four unresolved merge-conflict blocks**, which left it invalid JSON — and the file is transcribed into the OpenSSF Best Practices questionnaire, so an unparseable copy is a broken consumer rather than a stale number. It passed the doc-claim gate, CodeQL and 18 green checks, because `.bestpractices.json` is one of that gate's own `SCANNED_FILES` and every check it runs is a claim regex: a regex matches the first side of a conflict and never looks at the file's structure. Both sides of all four blocks were byte-identical, so the repair is lossless (verified by comparing the sides, not by choosing one). The gate now also runs `check_no_conflict_markers` and `check_scanned_json_parses`, both derived from `SCANNED_FILES` so a newly scanned file is enrolled with no further edit, and both failing closed on a file they cannot read. Only the **labelled** markers are matched (`<<<<<<< HEAD`, `>>>>>>> origin/main`) — a bare `=======` is a legal setext H1 underline in Markdown, and most scanned files are Markdown, so matching it would fail honest documents; a test pins that.
- **Any two PRs that added tests conflicted on six files, by construction — eliminated at the root** (#293). The collected test count was hand-carried as an exact figure in `.bestpractices.json`, `CLAUDE.md`, `CONTRIBUTING.md` (×2), `README.md` (×2) and `docs/ASSURANCE-CASE.md`, each checked for EQUALITY against whichever branch's own live `pytest --collect-only` count ran in CI. That count is a property of the post-merge tree, not of any one branch: two branches that each add tests compute two different, both-true numbers and must each edit the same six lines to match, so the second to merge silently overwrites the first's correct figure with its own now-stale one — measured on this repo as two red `main` runs (PR #280 synced to its own total, #278 added more tests against a stale base) and a PR rebased three times solely to resolve the resulting conflicts. `assets/badge-tests.svg` is now the ONLY artifact stating an absolute count; the five others point at it instead of restating the figure. The badge's own check moves from an exact match to a monotone **floor** (`doc_claim_structural.check_badge_floor`, `generate_repo_badges.stale_tests_badge`): a committed count that lags the live one is stale-but-true and passes, so a PR that only adds tests never touches it, and only an actual OVER-claim — a hand-typed number, or tests removed below what was claimed — fails. A standing regression guard (`test_no_prose_file_states_the_suite_size_any_more`) asserts no scanned file, including `.bestpractices.json`, states this claim in prose again. `check_doc_claims.py` (420 lines) and `generate_repo_badges.py` (305 lines) were both over the repo's 300-line file cap before this change needed to touch them further; split into `doc_claim_sources.py`/`doc_claim_scan.py`/`doc_claim_structural.py`/`repo_badge_catalog.py` (Extract Module) with zero behavior change, verified by an unchanged existing test suite before the floor logic was added.
- **`doc_claim_scan.py`, `doc_claim_structural.py`'s remaining functions and `repo_badge_catalog.py` — every mutant reported "no tests"** (#292), the last siblings in the `badge_render`/`check_badge_floor`/`doc_claim_sources` defect family (#262/#280/#293, and #235's own instance of it): `check_doc_claims.py` bare-imports the first two (`import doc_claim_scan`, `import doc_claim_structural`) and `generate_repo_badges.py` bare-imports the third, and a function's `__module__` is fixed at definition time to whatever name it was imported under (`mutmut/mutation/trampoline.py`, `module != decorated_func.__module__`) — never mutmut's dotted, path-derived `"scripts.<name>"`, so its trampoline never activated and every mutant in these three files showed "no tests" despite being exercised by real passing tests through the bare-imported path. Fixed the same way as the existing `check_badge_floor`/`doc_claim_sources` precedent: each sibling is loaded a second time via `importlib.util.spec_from_file_location("scripts.<name>", ...)`, and new direct-test classes (`DocClaimScanDirectTests`, `StructuralDirectTests` in `test_check_doc_claims.py`; `RepoBadgeCatalogDirectTests` in `test_generate_repo_badges.py`) call through those dotted references so mutmut's trampoline attributes the mutant to a real test. Verified with a real tally, not the absence of an error: a scoped `mutmut` run (`scripts/mutation_check.sh`) against `doc_claim_structural.py`, `doc_claim_scan.py`, `doc_claim_sources.py` and `repo_badge_catalog.py` plus both test files reports **301 mutants, 301 killed, 0 "no tests", 0 survived** — every assertion tightened to exact `assertEqual` (not `assertIn`) on the full message/dict, plus targeted `continue`-vs-`break` tests for multi-file scans for the loop-shaped survivors exact-match assertions alone don't reach. Boy-scout: `check_scanned_json_parses`'s `FileNotFoundError` branch (a missing scanned `.json` file) had no test at all, direct or indirect, before this change. Test-only; no production code changed.

- **`json_native.to_json_native`'s own committed mutation scope had 14 surviving mutants** (#250) — a third of `[tool.mutmut]`'s demonstrated example, the module written to guarantee the 2026-06-23 PG/SQLite `structuredContent` contract, had no test pinning it. 9 of the 14 were a real gap: the `tolist()`-failure debug log (`type(obj)`/`exc` args, and the format string itself) was never asserted, so a dropped arg, a swapped arg, or a reworded message all survived — `tests_py/shared/test_json_native.py::TestTolistFailureLogging` now forces the `tolist()` exception path and asserts the exact format string plus both args via `caplog`, killing all 9. The remaining 5 are **documented equivalents, not gaps**: `bytes.decode("utf-8", …)` vs `"UTF-8"` (codec lookup is case-insensitive — verified `codecs.lookup("utf-8") is codecs.lookup("UTF-8")`) and `typing.cast("SupportsFloat", obj)`'s type-hint string, which `inspect.getsource(typing.cast)` shows is `return val` — never read at runtime, so no test can ever observe a change to it. Both rationales are written at the use site (§12.1). Boy-scout: the function was already 48 lines against this repo's own 40-line convention before this change (and my initial fix pushed it to 60); split into `_decode_bytes`/`_coerce_number`/`_tolist_fallback` plus the dispatcher, each independently under 20 lines, with the existing 14 tests passing byte-for-byte unchanged as the behavior-preservation proof. Scoped mutation run: 43 → 51 mutants (the split creates more mutation sites), **0 surviving non-equivalent mutants**, same 5 equivalents renumbered under the new helpers.
- **The synaptic-plasticity modules could not be imported directly** (#233). `synaptic_plasticity.py` held the Tsodyks-Markram implementation AND back-imported its two siblings at the bottom of the file (behind `# noqa: E402`), while `synaptic_plasticity_hebbian.py` and `synaptic_plasticity_stochastic.py` imported names back out of it — a cycle. Whichever of the three was imported FIRST in a fresh interpreter decided whether the import worked: `python -c "import mcp_server.core.synaptic_plasticity_hebbian"` raised `ImportError: cannot import name 'apply_hebbian_update' from partially initialized module`, and `_stochastic` raised the same for `apply_stochastic_hebbian_update`. Fixed by extracting the implementation down into a new leaf, **`synaptic_plasticity_stp.py`** (Tsodyks-Markram state and dynamics, noise injection, theta-phase gating), whose only imports are `math`, `random` and `dataclasses`; the two siblings now depend on the leaf, and `synaptic_plasticity.py` becomes a pure re-export facade with the same 14-name `__all__`. The moved code is **byte-identical** to the lines it came from — no constant, equation or `# source:` comment was touched — so behaviour is unchanged (160 pre-existing tests across the plasticity, ablation-hook and consolidation-handler suites pass untouched). Both `# noqa: E402` markers are gone with the cycle that required them. **The suite was green throughout the whole time this was broken**, because pytest imports the facade first and every later import is a `sys.modules` cache hit — so the regression test (`tests_py/core/test_import_isolation.py`) runs each module in a **separate interpreter**; an in-process import cannot reproduce the class. On the pre-fix tree it fails 3 of 4. Mutation testing on the relocated code found the equations were pinned only by inequality assertions (29 of 128 mutants survived, e.g. `u * (1 - U)` → `u / (1 - U)`, `exp(-t/tau)` → `exp(-t*tau)`, `round(·, 6)` → `round(·, 7)`); 8 exact-value tests now kill 26 of them, and the 3 that remain are equivalent mutants documented with their rationale at the top of `test_stochastic_transmission.py`. Suite grows 6376 → 6388.
- **`update_concept` interpolated arbitrary dict keys into its SQL `SET` clause** — the one string-built-SQL site whose identifiers did NOT flow through an in-code allowlist (`docs/ASSURANCE-CASE.md` §5). Its single caller (`wiki_emerge`) passes literal keys, so no injection was reachable today, but the boundary itself enforced nothing: pre-fix, an injection-shaped key like `"label = 'x', status"` reached the SQL verbatim. Unknown keys are now REFUSED (`ValueError` before any SQL is built) against the `_UPDATABLE_COLUMNS` allowlist — the same refuse-not-escape mechanism as `wiki_view_executor._TABLE_WHITELIST` — and a DDL-drift guard test pins the allowlist to the `wiki.concepts` schema. Surfaced by the #197 family-4 S608 sweep. Tests: `tests_py/infrastructure/test_pg_store_wiki_concepts_allowlist.py`.
- **`narrative.extract_events` appended a spurious `"..."` when header-stripping shrank a memory below the snippet cap.** The ellipsis gate compared the RAW content length while the truncation applied to the CLEANED text, so an auto-captured memory whose stripped `# Tool:` header pushed the raw length over 150 chars was labelled truncated with nothing cut (`extract_decisions` was already correct). Latent bug surfaced by the #197 family-3 constant extraction, which made the two sites' asymmetry visible. Regression test: `tests_py/core/test_narrative.py::TestExtractEvents::test_no_spurious_ellipsis_when_cleaning_shrinks_below_cap`.
- **The doc-claim gate's own vacuity guard could be held open by a number that was never a claim.** `TEST_CLAIM` matches any `N tests` phrase in a scanned file, so an incidental count — "12 tests skipped locally that CI runs", a true and dated measurement — was read as an advertisement of the suite size. That line is not yet on `main`: it arrives with #231, whose `Test (Python 3.12)` leg fails today on exactly `CONTRIBUTING.md:36: advertises 12 tests` while its `Lint` leg passes, because the static gate skips the test-count family when no `--test-count` is given. This change is therefore the build-first half of that pair — it lands the mechanism, and #231 declares the marker on its own line. Two defects followed, and the second is the dangerous one: the false positive *counted as a match*, so `check_counts`' vacuity guard (the thing that turns a reworded or deleted claim into a build failure rather than an unnoticed loss of coverage) stayed silent. Probed on the pre-fix code: a tree whose only `N tests` text was that incidental line returned a mismatch, not the vacuity message — every real `6268 tests` claim could have been deleted and the guard would not have fired. A line whose number counts something else now declares `[not-a-count-claim: <label>]` and is skipped **for that family only**, so the same line still answers to every other one; the prose keeps its number, its date and its breakdown, because rewording a true measurement to keep a gate quiet hides the measurement instead of fixing the gate. Declared exemptions form a registry that is printed on every successful run and pinned by name in a test, so an exemption is added deliberately or not at all, and the marker fails closed — a misspelled or wrong-family label exempts nothing. Also folded away a second, hand-rolled copy of the vacuity guard for the with-integrations tool claim, which had no test of its own; it now runs through `check_counts` like every other family and has one. Scoped mutation run: **0 surviving mutants on the changed code** (`collect_failures` went 45 → 0 once the composition was driven against a deliberately stale repository rather than only the green real tree); 25 survivors remain in the untouched `canonical_*` helpers, filed as #235.
- **The test-count family was checked in exactly one place on earth.** `collect_failures` skips `TEST_CLAIM` entirely when no `--test-count` is passed, and only the Python 3.12 matrix leg of the test job passes one — so the repository-level test that runs everywhere never exercised the most drift-prone claim in the project, and five of the six CI jobs were blind to it. `test_every_advertised_test_count_states_the_same_number` asserts instead that every advertised count *agrees with the others*, which needs no live `pytest --collect-only` and therefore runs in the local suite and in all six jobs; a half-updated count now fails before it reaches CI.
- **`scripts/` was unreachable by the mutation runner**, so no gate, hook or helper under it had ever been mutation-tested. Three things blocked it: `[tool.mutmut] source_paths` was `mcp_server`-only (a source outside it is silently never mutated, and the run then reports zero survivors because it mutated nothing); `also_copy` omitted the documentation surface, so a module that resolves repository files relative to its own location raised `FileNotFoundError` under every mutant; and the test loaded the gate under a bare module name while mutmut keys its trampolines on the dotted path, which made every mutant look unreached. `scripts/mutation_check.sh` now unions the sources' roots into `source_paths`, `also_copy` carries the files the gate reads, and the test loads it as `scripts.check_doc_claims`.
- **`scripts/mutation_check.sh` false-reported 50 survivors for `ast_extractor_registry.py`'s `_make_extractor`/`build_extra_extractors`** (#269) — mutmut's per-mutant test attribution is recorded once, from a coverage trace of the FIRST test whose call reaches the mutated line; `ast_parser._EXTRACTORS = {..., **build_extra_extractors()}` builds its dispatch table once, eagerly, at import time, so every test after the first exercises the already-built, cached closures without ever re-invoking the mutated functions — mutmut narrowed the per-mutant rerun to one (often irrelevant) test and reported "survived" for all 50 mutants even though the full 3-file test selection genuinely kills every one. `scripts/mutation_recheck_survivors.py` closes the gap generically, for any source, not by special-casing this one file: every mutant mutmut reports "survived" is re-run against the FULL declared test selection before the verdict is trusted, and a mutant the full selection kills is reported as **RECOVERED** — a distinct, visible category, never silently folded into "killed" (a false-survivor report otherwise either blocks a correct commit or trains reviewers to wave off real survivors as "probably a tooling artifact"). `scripts/mutation_check.sh` also gained multi-file test-selection support (`<test_paths>` now accepts a space-separated list), needed because `_make_extractor`/`build_extra_extractors` require `ast_parser.py`'s own repeatedly-called functions in the same run for mutmut's OWN forced-fail bootstrap check to succeed at all (mutating `ast_extractor_registry.py` alone starves that check of anything to re-invoke). Re-running the full reproduction surfaced ONE genuine (non-false) survivor mutmut's current version generates that the issue's original reproduction did not: `_make_extractor__mutmut_10` replaces the `source` argument to the calls-extractor with `None`, invisible to every existing per-language test because `extract_calls_generic`'s hardcoded node-type list (`"call"`/`"call_expression"`) never matches any of the 7 languages' own call-expression node type (Java's is `method_invocation`, for instance — a separate, pre-existing, out-of-scope language-coverage gap); a new test (`test_make_extractor_threads_the_real_source_into_calls_extraction`) monkeypatches `extract_calls_generic` to assert `_make_extractor`'s own composition contract directly, closing it. Verified: 0 genuine survivors remain in `ast_extractor_registry.py`; `json_native.py`'s existing scoped run is unchanged (same 5 documented-equivalent survivors); `scripts/mutation_recheck_survivors.py` itself carries **0 surviving mutants** on its own committed scope (32 new tests). *(Retired below, same [Unreleased]: the ast_parser dead-code-removal entry deletes `extract_calls_generic` and its call site outright, so `_make_extractor__mutmut_10` can no longer be generated and the test this paragraph added is removed with it — see `tests_py/core/test_ast_extractors_multilang.py`'s in-file note at the deletion site.)*
- **An unreadable wiki `README.md` was overwritten instead of preserved.** `wiki_store._try_reindex` promises "never clobber a hand-written README", but when the marker check could not read the file (permissions, non-UTF-8 bytes) the failure was swallowed and `should_write` stayed `True` — the README was replaced with generated content. Surfaced by the #197 S110 sweep; an unreadable README is now left untouched and the read failure is reported via `silent_failure` (`wiki_store.readme_read`). Regression test: `tests_py/infrastructure/test_s110_sweep_infrastructure.py::TestWikiStoreReadmeGuard::test_unreadable_readme_is_not_clobbered`.
- **The wiki pipeline was silently dead on the SQLite backend** (#206) — the default for plugin installs, `.mcpb`/Cowork, and every sandboxed launch (`PRIVACY.md` lines 26–38). `PsycopgCompatConnection` exposed no `cursor()`, so all six stages (`extract → resolve → emerge → synthesize → curate → compile`) and `wiki_migrate` raised `AttributeError`; each error was captured as a string and `backfill_memories` returned a **success-shaped payload with zero pages and no log line** — the FlashRank silent-failure mode a third time. A fresh SQLite install reported a successful backfill and produced no wiki. The **entire `wiki` schema is now ported to SQLite** (`infrastructure/sqlite_schema_wiki.py`: the eight `wiki.*` tables flattened to `wiki_*`, since SQLite has no schema namespaces, plus every index except the PostgreSQL-only HNSW/GIN families), and the compat layer grew the translations the shared SQL actually needs: `cursor()` (context-managing, dict-returning, accepting psycopg's `row_factory=`), `%(name)s` → `:name`, `wiki.<t>` → `wiki_<t>`, `array_length(c,1)` → `json_array_length(c)`, `= ANY(?)` and `&&` → `json_each` membership/intersection tests, `::int[]` casts (the trailing `[]` included), `IS DISTINCT FROM` → `IS NOT`, `UPDATE t alias` → `UPDATE t AS alias`, and `RETURNING id, (xmax = 0) AS inserted` → `RETURNING id` (kept natively on SQLite ≥ 3.35, because `lastrowid` does not identify the row an upsert *updated*). `INTEGER[]`/`JSONB` columns are declared `JSON` and round-trip through a registered converter/adapter pair, so `entity_ids` returns a `list[int]` as psycopg gives — without it the column returned `"[1,2]"` and `for eid in entity_ids` would have iterated **character-wise**, yielding garbage ids and never raising. Two of the defects made stages *report success while doing nothing*: untranslated `%(name)s` extracted **zero claims**, and `wiki_resolve`'s `WHERE entity_ids = '{}'` (PostgreSQL's empty-array literal, which never matches SQLite's `'[]'`) made resolution a **permanent no-op** — that predicate is now the backend-agnostic `COALESCE(array_length(entity_ids, 1), 0) = 0`, and `wiki_emerge`'s bare `COUNT(*)` is aliased, since psycopg names that column `count` and SQLite names it `COUNT(*)`. Both `wiki_pipeline._safe_call` and `backfill_memories`' pipeline `except` clause now **log** the failure instead of only recording it. Verified end-to-end on SQLite (4 memories → 3 claims → 3 concepts → 3 drafts → 3 published pages) against a paired PostgreSQL control on the same commit; existing SQLite databases gain the tables on next open via the `CREATE TABLE IF NOT EXISTS` init path, no shim.
- **The stage-aware context assembler dropped memories it had selected, instead of condensing them** (#196). Its own contract reads "may truncate individual chunks but never reduces the count of selected items"; the code did the opposite — Phase 2 skipped any memory that did not fit the remaining budget and Phase 3 broke out of its loop, so the longest memories (the ones retrieval had just ranked highest) vanished from both the rendered text and `selected_memories`, while Phase 1's 60 % share was never computed at all. Measured pre-fix with two ~760-token adjacent memories at a 120-token budget: zero phase-2 memories and empty adjacent text. The domain-aware condensers in `core/context_assembly/condensers.py` were written for exactly this reduction and had no caller — they are now the packing rule's reduction step (`core/context_assembly/stage_phases.py`), giving every item a share of the budget (the Swift ContextDecomposer rule, now a single definition in `budget.proportional_share`) and condensing the over-share ones. One output per input, never a drop. Behaviour is unchanged when `token_budget is None`, which is what every current caller passes. Also fixed: `condense_assistant_message` could return an empty string — a single code block larger than the whole budget kept no blocks and joined an empty list, deleting the memory outright — and now falls back to `truncate_to_budget` like every sibling condenser.
- **The reranker can no longer hang a process on a stalled model download** (`CORTEX_RERANKER_OFFLINE`). FlashRank fetches its ONNX weights with a bare `requests.get(..., stream=True)` carrying **no timeout**, and it bypasses the `huggingface_hub` client entirely — so `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` never reached it, and a stalled TCP connect blocked the calling thread indefinitely rather than raising, which meant `_ensure_reranker`'s `except Exception` (the 2026-07-10 incident's fix) could not engage. This was not hypothetical: CI run 30263190266 (main, Python 3.12→3.13 leg, 2026-07-27) hung inside `sock.connect` during a recall test until pytest-timeout killed the entire suite at 300s, while every other matrix leg happened to download fine — an intermittent red build whose frequency scales with how cold the cache is. Setting `CORTEX_RERANKER_OFFLINE` to a truthy value now refuses the download when the cached model file is absent and takes the existing, already-tested degraded path (first-stage WRRF scores only, with a warning naming the variable and the exact path it expected). **Production behaviour is unchanged** — the variable is unset by default, so FlashRank's documented first-run self-provisioning download (`PRIVACY.md`) still happens; air-gapped installs gain a real switch. CI now caches `~/.cache/flashrank` and pre-downloads the model in a loud, retrying step (mirroring the embedding model's), then sets the variable for the test steps so no download can ever occur mid-suite.

### Security

- **`transformers` 4.57.6 → 5.14.1, closing all 30 open Dependabot alerts** (#257; supersedes Dependabot's #255/#256). Three advisories require `>= 5.5.0`: GHSA-fgcw-684q-jj6r (high), GHSA-29pf-2h5f-8g72 (high), GHSA-69w3-r845-3855 (medium). `transformers` is not a direct dependency — it arrives through `sentence-transformers` — so the bump belongs in `uv.lock`, the single source of truth from which `scripts/generate_pip_constraints.py` exports every `requirements/*.txt`. Dependabot edited only the exported files, which left `huggingface-hub` at 0.36.2 against transformers 5's `>=1.5.0,<2.0` floor; that is a `ResolutionImpossible` on every job that installs dependencies, and a lock/export disagreement on Lint. Relocking moves the cluster coherently: `huggingface-hub` 0.36.2 → 1.25.1, `datasets` 2.14.4/5.0.1 → 5.0.1 (the `<3.11` fork existed only to hold `huggingface-hub<1.0`), plus `typer`/`shellingham`/`annotated-doc` as new transitive dependencies of transformers 5 — every one `requires-python >= 3.10`, matching this project's floor. `sentence-transformers` stays 5.6.1 (it declares `transformers<6.0.0,>=4.41.0`) and FlashRank is untouched (it depends on `tokenizers`/`onnxruntime`, never on transformers). **`TRANSFORMERS_OFFLINE` keeps working**: transformers 5 no longer reads it, but `huggingface_hub` 1.25.1 does (`HF_HUB_OFFLINE = _is_true(os.environ.get("HF_HUB_OFFLINE") or os.environ.get("TRANSFORMERS_OFFLINE"))`), so CI's offline test runs are unaffected.
- **The embedding model's end-to-end behaviour is now asserted, not assumed** (#257). Every prior embedding test mocked `SentenceTransformer`, so a dependency bump could break the real model without turning a single test red — and two mechanisms would have hidden it: `_finalize_loaded` silently overwrites the requested dimension with whatever the model reports, and every non-`LOADED` state degrades to the algorithmic fallback, which also returns 384-dim L2-normalised vectors. `tests_py/infrastructure/test_embedding_live_contract.py` loads the real `all-MiniLM-L6-v2` through the production engine and asserts neural provenance (`ModelState.LOADED`, `mode == "neural"`), dimension 384, determinism across engine instances, batch/single agreement, and that paraphrases outrank unrelated text. It **fails** rather than skips when the model is unavailable under `CI`, where the pre-download step guarantees the weights.
- **The launcher's hand-restated pins are reconciled against the lock, and the reconciliation is executable** (#257). `scripts/launcher_deps.py` restates a slice of the resolved set so a plugin bootstrap can install without a resolver; nine of its eleven pins had drifted from the `uv.lock` they cited (`fastmcp` 3.2.4 vs 3.4.5, `sentence-transformers` 5.4.1 vs 5.6.1, `pgvector` 0.4.2 vs 0.5.0, `psycopg` 3.3.3 vs 3.3.4, `pydantic` 2.13.3 vs 2.13.4, `pydantic-settings` 2.14.0 vs 2.14.2, `psycopg-pool` 3.3.0 vs 3.3.1, and a numpy fork table that still described a two-way split the lock had made three-way). A plugin install therefore resolved a combination no CI job exercised. The pins move to `scripts/launcher_pins.py` (third stdlib-only sibling, same SRP split as `launcher_deps_fs`/`launcher_deps_install`), numpy becomes a data table instead of an `if/elif` chain so branches the running interpreter does not take are still checkable, and `tests_py/scripts/test_launcher_pins_match_lock.py` fails whenever the pins and `requirements/setup.txt` disagree — on every supported Python, not just the leg's own.
- **Every dependency install is hash-pinned, and the two that could not be pinned were replaced** (#203; closes all 21 OpenSSF Scorecard Pinned-Dependencies alerts). An exact version is **not a pin**: `foo==1.2.3` still resolves to whatever the index serves under that version today, and only a hash pins the bytes — which is what Scorecard's check encodes and why `ruff==0.15.20` and `torch==2.11.0` counted as unpinned. `pip install --require-hashes` is all-or-nothing, so it needs a resolved lock; **`uv.lock` becomes the single source of truth** and `scripts/generate_pip_constraints.py` exports one hashed file per call site into `requirements/`, refusing an export that is empty or carries an unhashed requirement. `--check` is a blocking Lint step, so a lock change that is not re-exported fails there instead of at install time. All 21 sites rewired: `ci.yml` ×7, `release.yml` ×2, `scripts/setup.sh`, and the three Dockerfiles. The project itself installs `--no-deps` against the hashed set; the root image builds a **wheel** instead, because an editable install leaves a `.pth` pointing at a build directory the runtime stage never copies. CI tool pins (ruff, pyright, build+hatchling) moved into `[dependency-groups]` so they are locked rather than restated as bare version strings in two workflow files — `hatchling` is pinned too, since `python -m build` with isolation would otherwise fetch the build backend from PyPI mid-build, outside every hash check. **The CPU-only torch build is now described by the lock**: the containers passed `--index-url https://download.pytorch.org/whl/cpu` at the call site, so `uv.lock` recorded PyPI's artifact while the image installed a different one and no source of truth could produce a hash for what was actually installed. `[[tool.uv.index]]` + `[tool.uv.sources]` bind torch to that index on Linux; the lock now carries `torch 2.13.0+cpu` with 22 hashes and resolution **drops 18 nvidia/cuda packages plus triton**. torch is named in a `container` dependency-group purely so the source can bind to it — PEP 735 groups are not published, so nothing changes for anyone installing `hypermnesia-mcp` from PyPI. The two non-pip findings had to stop being what they were rather than be pinned: `docker/Dockerfile` piped `https://deb.nodesource.com/setup_22.x` **into bash** — an unreviewed remote script executed as root at build time, with no hash to check a pipe against — and now does what that script does (fetch the signing key, register the signed apt source, install the signed package, with curl feeding `gpg --dearmor`, which executes nothing); and `npm install -g @anthropic-ai/claude-code` was **unversioned**, so the image tracked whatever the registry served that minute, and is now `npm ci` against a committed lockfile that records a sha512 integrity hash for every transitive package. **Making the lock the install source exposed a latent defect in the lock itself**, which is the point of doing it: `uv.lock` had `onnxruntime 1.24.3` recorded for the `python_full_version < '3.11'` fork, and onnxruntime 1.24.x publishes no cp310 artifact and no sdist (1.24.3 ships 24 files whose lowest interpreter tag is cp311; 1.24.0 declares no `Requires-Python` at all, which is why uv accepted it there). The entry was already on `main` and stayed invisible because `main` installs from `pyproject.toml`, where pip quietly re-resolves onnxruntime down to 1.23.2 on 3.10 — a hash-pinned install cannot, so `Test (Python 3.10)` died with `No matching distribution found for onnxruntime==1.24.3`. Fixed at the lock with a `[tool.uv] constraint-dependencies` entry (`onnxruntime<1.24 ; python_full_version < '3.11'`) rather than at the workflow: constraints steer only our resolution and are never published in the wheel metadata, so consumers on 3.11+ still resolve the current onnxruntime. Every requirements file was then re-checked with `pip install --dry-run --require-hashes` on **linux/amd64** against each Python its consumers actually use, and onnxruntime was the only package in the set with this defect.
- **Coverage-guided fuzzing** (closes the Scorecard Fuzzing alert). Two harnesses in `fuzz/` over pure parsers that read untrusted text (§13.1 D2 — LLM-generated content is untrusted): the hand-rolled YAML frontmatter parser and the wiki source-path canonicaliser. Wired to **ClusterFuzzLite** (`.clusterfuzzlite/`, `.github/workflows/fuzz.yml`) — a 120s batch on PRs that blocks, and a longer scheduled run that does not, because a fuzzer left running will eventually find something and holding the merge queue hostage to an unrelated input makes the check ignored within a week. Writing the path harness **found a live bug**: `normalize_source_path` stripped `./` in a loop and then `/` exactly once, so removing the slashes could expose a `./` the loop had already walked past — `.//./x` came out as `./x`, still carrying the prefix the function exists to remove, and not idempotent. `extract_document_paths` dedupes on that result, so one document reachable by two spellings counted as two. Fixed by iterating to a fixed point; the four reproducers are committed as corpus inputs and **fail on the pre-fix code**. `fuzz/replay_corpus.py` runs every corpus input through its harness with no atheris, so the properties execute in the ordinary `pytest` suite on every platform — atheris publishes manylinux x86_64 wheels for cpython 3.12–3.14 and nothing else, and a property only one CI job can run is one that rots.

- Destructive tools (`forget`, `wiki_purge`, `wiki_migrate`) are **gated, not merely hidden** under `lean` (#177 criterion 5): excluded tools are absent from `tools/list` AND rejected on call by `ToolProfileMiddleware.on_call_tool`. Hiding a tool from the list while still executing it on call would be a hole, not a token optimisation. Asserted by `tests_py/test_tool_profiles.py::TestSurface::test_lean_hides_and_rejects_destructive_calls`.

## [4.16.0] - 2026-07-25

### Added
- **Native prose-redaction pass for generated prose** (#166, #167): `core/prose_redaction.py` carries a 16-class mechanical inventory of AI-writing tells with per-pattern sources (Wikipedia "Signs of AI writing"; method prior art blader/humanizer and petergyang/no-ai-slop, MIT; house rules) — em dashes, banned vocabulary, weasel attribution, filler, -ing tack-on analyses, binary contrasts, negative listing, throat-clearing, faux insight, importance puffery, promotional language, fake-strong verbs, AI conversation artifacts, signposting, rhetorical setups, dramatic fragmentation. All three wiki-authoring prompts (topical, coverage, re-author) now embed `REDACTION_CONVENTIONS` so tells are avoided at generation time; `wiki_write` returns an advisory `redaction_findings` summary (never blocking, omitted when clean) so every generated page is measured at write time. Judgment-level tells (synonym cycling, rule of three, colon reveals in context) stay at prompt time by design; the mechanical set is FP-guarded by tests asserting ordinary technical prose stays silent. User-authored content is out of scope.


## [4.15.0] - 2026-07-22

The plugin is renamed **`cortex` → `hypermnesia-mcp`** (a community-directory name collision with an unrelated `cortex` plugin; the new name matches the existing PyPI / MCP-registry identity). Existing users: `claude plugin uninstall cortex && claude plugin install hypermnesia-mcp` — memories and configuration are untouched, storage paths do not change. A minimal `cortex` deprecation shim (`plugins/cortex-deprecated/`) stays on the marketplace and announces the migration at session start.

### Added
- SQLite-first plugin install — full hook experience with zero system PostgreSQL; PostgreSQL stays the opt-in upgrade and existing installs are never downgraded (#160).
- "Use with other MCP hosts" README section (Gemini CLI, Codex, Cursor, Windsurf, VS Code) + `gemini-extension.json`.
- `cortex` deprecation shim plugin entry on the marketplace (SessionStart migration notice only, no functional hooks).

### Fixed
- Write-gate decision/error/success bypass cues are language-aware instead of English-only, so deliberate multilingual writes are no longer rejected by the novelty gate (#158, #161).
- Three setup-run bugs (#163): entity names are deduplicated at the `discover_causal_edges` boundary, establishing the PC algorithm's distinct-variables precondition (duplicate names produced degenerate edges that crashed the 2-tuple unpack); the SQLite backend (the plugin default) now implements the grooming surface (`get_grooming_ages` + promotion count), so `memory_stats` and `get_grooming_health` no longer crash; and the scanner reads `FrontmatterResult` by attribute instead of string-key indexing — every legacy memory `.md` parse raised a swallowed `TypeError`, so legacy-memory imports silently did nothing.

### Changed
- Plugin renamed `hypermnesia-mcp`; hardcoded old-name paths updated (`scripts/install-plugin.sh` / `scripts/update-plugin.sh` marketplace-cache paths, `doctor_mcp.py`'s `hypermnesia-mcp@cortex-plugins` registry key, the cortex-import skill's plugin-data dir).

### Verified
- Pre-tag guard on the release tree (`benchmarks/reproduce.sh --no-ablation`, isolated ephemeral pgvector container, `reranker_state: "loaded"` in both MANIFESTs, same pinned embedding revision): LongMemEval-S MRR **0.9150** (floor 0.914, +0.0010 PASS) / R@10 **0.9820** (floor 0.982, +0.0000 PASS); LoCoMo single-run MRR **0.8008** (floor 0.805 tol 0.005, -0.0042 PASS — matches the v4.14.3 3-run mean 0.7998 within its standard error) / R@10 **0.9132** (floor 0.915, -0.0018 PASS); BEAM-100K MRR **0.5453** (not gated, inside the documented 0.539–0.547 noise band). Protocol note: the runner process was killed externally right after BEAM startup (LongMemEval + LoCoMo results already written); the run's remaining steps (`write_manifest`, `check_floors`) were executed with the script's own functions against the run's still-live container, and BEAM was completed as a separate `--only beam` run with its own container and MANIFEST. Evidence: `benchmarks/results/repro/20260722-v4.15.0-pretag/`.

## [4.14.3] - 2026-07-17

### Fixed
- `write_class="deliberate"` (or omitted, source-fallback) was rejected by the novelty gate, violating the documented contract that deliberate writes are never rejected for low novelty. `write_class` is now threaded through `evaluate_gate` / `_compute_gate_decision` / `determine_bypass`, checked last so a more specific content-based bypass reason (`bypass_error`/`bypass_decision`/`bypass_important_tag`) still wins when it applies (#147, #148).
- `force=True` (and plain) writes intermittently raised a misleading "check DATABASE_URL" hint on a bare `FileNotFoundError` — root cause was `validate_memory.grade_from_content(base_dir=os.getcwd())` in the write-time provenance grading step, unguarded unlike every sibling enrichment step, raising when the process cwd had been removed mid-session (e.g. a worktree cleanup), unrelated to the DB. Wrapped in the same defensive try/except pattern used elsewhere; `tool_error_handler.py`'s blanket DATABASE_URL hint no longer fires for exception types it doesn't recognize as DB-related (#147, #148).
- Issue #149's Python-3.10-only flake: `pip_install`'s per-entry commit loop pruned superseded `*.dist-info` siblings immediately after each entry committed. `os.listdir()` order is unspecified by the stdlib and differs by OS/filesystem, so the prune could permanently delete the still-valid OLD dist-info right before the package-directory entry failed and rolled back, leaving `deps_dir` with reverted package files but no metadata for either version. The destructive prune now waits until the whole `tmp_dir` commits successfully, independent of listdir enumeration order (#149, #150).

### Changed
- `mcp` dependency bumped 1.27.0 -> 1.28.1 (uv group, dependabot) (#152).
- `wiki_classifier.py` and `wiki_axis_registry.py` split into cohesive collaborators (`wiki_axis_defaults.py`, `wiki_classifier_gates.py`, `wiki_classifier_patterns.py`, `wiki_kind_detection.py`, `wiki_title.py`) to bring both files under the repo's 500-line limit; no behaviour change (#134, #153).

### Verified
- Pre-tag guard on the exact release tree `4e3a202b` (`benchmarks/reproduce.sh --no-ablation` + 2× `--only locomo`, isolated ephemeral pgvector containers, `reranker_state: "loaded"` in all 3 MANIFESTs, same model sha256): LongMemEval-S MRR **0.9166** (floor 0.914, +0.0026 PASS) / R@10 **0.9820** (floor 0.982, +0.0000 PASS); LoCoMo 3-run mean MRR **0.7998** (reps 0.8013 / 0.7983 / 0.7997) / R@10 **0.9135** (reps 0.9142 / 0.9127 / 0.9137, floor 0.915 tol 0.005 PASS); BEAM-100K MRR **0.5417** (not gated, inside the documented 0.539–0.547 intra-day noise band). Evidence: `benchmarks/results/repro/20260717-v4.14.3-pretag/`.
- Adjudication (LoCoMo MRR mean 0.7998 vs threshold 0.800 = floor 0.805 − tol 0.005, i.e. −0.0002): accepted as sampling noise by explicit maintainer decision (2026-07-17). Grounds: delta vs the v4.14.2 pre-tag mean (0.8009) is −0.0011, below the standard error of a 3-rep mean (~0.0013, single-rep stdev 0.0022 per the floors-rebaseline data); rep1 under the identical full-run protocol reads 0.8013 vs 4.14.2's 0.8015; the reranker is verified loaded in every run (FlashRank-absence signature excluded); and none of the 4 released commits is in the LoCoMo harness's dependency graph — ingestion goes through `BenchmarkDB`, not the #148 write path (`benchmarks/lib/bench_db.py`). Symmetric precedent: v4.14.1 released at +0.0002 above the same threshold. #150/#152/#153 do not touch the recall path reproduce.sh's floors exercise; #148 touches the write-gate (write path) — the empirical floor-gate result above is the actual non-regression evidence, not an import-closure argument.

## [4.14.2] - 2026-07-15

### Fixed
- The 3 pre-existing `core → infrastructure` layer violations tracked since #114 (`wiki_axis_registry.py`, `wiki_classifier.py`, `wiki_schema_loader.py` importing `infrastructure.config`/`infrastructure.wiki_schema_reader` directly) are closed via reverse-DI ports-and-adapters — core now declares a zero-arg wiki-root/user-rules provider port, wired at the `mcp_server/__main__.py` composition root; no behaviour change (#135).
- Explicit XDG-aware `cache_folder` passed to `SentenceTransformer` instead of relying on the library default, closing a residual `/tmp`-caching risk class (#132).
- Stale hard-coded module counts in `docs/architecture.md` replaced with a single-source pointer to `docs/module-inventory.md` (#130).
- Windows `postInstall` dispatch routed through the cross-platform `setup.py` path, with the real install path now exercised in CI (#117).
- Stale "production database" bench-gate claim in `CLAUDE.md`/docs fixed; LoCoMo intra-day noise caveat documented alongside the isolated-container `reproduce.sh` gate (#121).

### Added
- `check_setup` MCP tool exposed as a facade over `mcp_server.doctor` for in-session install diagnosis, plus a `/preflight` command that turns the 7-check output into a dependency-ordered repair plan (#115, #119).
- Project settings catalogue + headless CI regimes (#131).
- One-command devcontainer (`.devcontainer/`) with pgvector + prewarmed embedding/reranker models (#129).
- Optional OTLP telemetry exporter, OFF by default — mirrors the existing local, content-free `get_telemetry` aggregate metrics to a configured `OTEL_EXPORTER_OTLP_ENDPOINT` (#128).

### Changed
- `CLAUDE.md` refactored to under 200 lines, resyncing storage-truth prose against `PRIVACY.md` (#125).
- Corporate proxy/CA setup for model downloads documented (#123).

### Verified
- Pre-tag guard on the exact release tree (git_sha `018c76d7`, `benchmarks/reproduce.sh --no-ablation`, isolated ephemeral pgvector container, reranker loaded): LongMemEval MRR 0.9166 / R@10 0.9820 (matches v4.14.1 0.9167/0.982 — no regression, retrieval code untouched by the 13 commits since v4.14.1). LoCoMo 3-run mean MRR 0.8009 / R@10 0.9146 (runs: 0.8015/0.9168, 0.8004/0.9142, 0.8006/0.9127 — vs v4.14.1's 3-run mean 0.7984/0.9142, an improvement within the documented same-commit noise band, not a regression). BEAM MRR 0.5437 / R@10 0.7139 (vs v4.14.1's 0.5406 — within the 0.539–0.547 intra-day production-DB variance band established in v4.14.1's own investigation; BEAM is a proxy metric not gated by `check_floors`).
- Floor-gate result (`reproduce.sh::check_floors`, tolerance 0.005): LongMemEval R@10 0.982 vs floor 0.982 PASS; LongMemEval MRR 0.9166 vs floor 0.914 PASS; LoCoMo R@10 0.9146 (mean) vs floor 0.915 PASS (individual reps 0.9168/0.9142/0.9127, each within tolerance); LoCoMo MRR 0.8009 (mean) vs floor 0.805 PASS (-0.0041, within the 0.005 tolerance — each individual rep also passes, unlike v4.14.1 where rep1 alone read FAIL). Reranker active (`reranker_state: loaded`). Evidence: `benchmarks/results/repro/20260715-v4.14.2-pretag/` (5 files: longmemeval-s.json, locomo-rep{1,2,3}.json, beam-100K.json, MANIFEST.json), matching the v4.14.1 evidence-directory convention.

## [4.14.1] - 2026-07-14

### Fixed
- **MCP tool errors are diagnosable again.** `safe_handler` now raises `ToolError` on handler failure instead of returning a schema-violating error dict; a failing tool call surfaces its real diagnostic (a Postgres constraint violation, a missing file, etc.) instead of the generic "Output validation error" every client previously saw regardless of the underlying cause.
- `wiki.pages` frontmatter parsing strips quoted/duplicated-label scalar values that previously broke FS↔PG sync (#104).
- `wiki_migrate --dry-run` made transactionally neutral — a dry run no longer leaves partial state behind (#108).

### Added
- `write_governed_page` validates and normalizes frontmatter at write time instead of only at read time, closing the gap that let malformed frontmatter reach disk in the first place (#109).

### Changed
- `wiki_pages.py` refactored into cohesive collaborators (`wiki_frontmatter.py`, `wiki_frontmatter_validation.py`, `wiki_index.py`, `wiki_page_builders.py`) — no behaviour change (#111).

### Verified
- Pre-tag guard on the exact release tree: LongMemEval MRR 0.9167 / R@10 0.982 (matches v4.14.0 0.9166/0.982); LoCoMo 3-run mean MRR 0.7984 / R@10 0.9142 (v4.14.0 was 0.8005/0.9131 — Δ MRR -0.0021 is smaller than v4.14.0's own documented ±0.0025 single-run variance, not a regression; R@10 improved); BEAM 0.5406 (3 runs, spread 0.0001) vs v4.14.0's 0.5471 — investigated via a same-day, same-production-DB A/B against a control worktree pinned at v4.14.0: a same-day v4.14.0 rerun measured 0.5445 then, on a second rerun ~2.5h later, 0.5391 — the SAME tree spans the same 0.539–0.545 band as v4.14.1, and a bisect at 53712df8/49f29e98 landed inside that band with no monotonic step at any commit boundary. Combined with a diff of the full mcp_server change-set between v4.14.0 and this tag (confined to `wiki_*`, `handlers/consolidation/page_io.py`, `handlers/wiki_migrate.py`, `handlers/wiki_write.py`, `tool_error_handler.py` — none of which is in the `memory_ingest`/`pg_recall`/`reranker` import closure any retrieval benchmark exercises), the BEAM deviation is intra-day production-DB variance, not a code effect. BEAM is not gated by `reproduce.sh`'s floor check (proxy metric, within-system comparison only), so this does not block the tag.
- Floor-gate result (`reproduce.sh::check_floors`, tolerance 0.005): LongMemEval R@10 0.9820 vs floor 0.9820 PASS; LongMemEval MRR 0.9167 vs floor 0.9140 PASS; LoCoMo R@10 0.9142 vs floor 0.9150 PASS; **LoCoMo MRR 0.7984 vs floor 0.8050 FAIL** (-0.0066, exceeds the 0.005 tolerance) — flagged, not hidden: this fails the codebase's hardcoded absolute floor while passing the release's actual stopping rule (no regression beyond noise vs the v4.14.0 baseline). The absolute floor has not been re-baselined since the 4.11–4.13 measurement era and LoCoMo MRR has trended down release-over-release with no corresponding retrieval-code change, suggesting the floor itself needs recalibration in a future session — ideally measured against an isolated benchmark DB rather than the live growing production store used here. Reranker active. Evidence: `benchmarks/results/repro/20260714-v4.14.1-pretag/` (11 files: the 5 primary runs, beam-100K-rep2/rep3, and 4 investigation runs).

## [4.14.0] - 2026-07-13

### Added
- **Standalone schema-migration entry point** (`python -m mcp_server.migrate`). Brings a PostgreSQL store's schema current by reusing `PgMemoryStore`'s existing hash-gated, advisory-lock-serialized DDL apply path — no duplicated DDL, no MCP server boot. Frozen contract (consumed by the cortex-viz plugin): `DATABASE_URL=<url> python -m mcp_server.migrate` → exit 0 (`schema up to date` | `applied N statements`) / exit 1 (one-line stderr reason). cortex-viz 2.6.1's `open_visualization` preflight invokes it to migrate an outdated store before building the graph, surfacing an actionable message instead of a silently empty graph when it can't.
- **`wiki_migrate` MCP tool + wiki.pages↔filesystem reconciliation**: backfill, ghost purge, and a parity guard keep the `wiki.pages` table and the on-disk wiki in sync. Standalone tool count 49 → 50 (53 with upstream integrations).

### Fixed
- `wiki.pages` `pages_status_check` widened to the full system-emitted status union — interactively-authored pages carrying a valid-but-unlisted status no longer fail the FS↔PG sync.

### Changed
- Docs and marketplace tool count corrected to the measured ground truth (50 standalone / 53 with upstream integrations).

### Verified
- Pre-tag guard on the exact release tree: LongMemEval MRR 0.9166 / R@10 0.982; LoCoMo 3-run mean MRR 0.8005 / R@10 0.9131 (single-run variance ±0.0025 straddles the 0.805 floor; the mean clears the 0.005 tolerance and matches the 4.13.3 baseline 0.8017 / 0.9152 on identical, retrieval-orthogonal code); BEAM 0.5471; reranker active; all gated floors PASS.

## [4.13.3] - 2026-07-12

### Fixed
- **Third-party inspection contract restored — every registry indexer had been failing silently for ~2 months.** `psycopg` is an optional dependency (`[project.optional-dependencies].postgresql`), yet 22 `mcp_server/infrastructure/pg_store_*.py` modules imported it unconditionally at module top-level — so any bare install (`uv sync` + `uv run`, exactly glama.ai's sandbox build path, and any fresh-environment first try) crashed at import time, before `tools/list` could ever answer. All 22 modules now import psycopg under `TYPE_CHECKING` or function-locally (the lazy pattern 3 hook modules in this repo already used); the DB-less standalone surface (49 tools) registers cleanly with zero environment. Root-caused from a live reproduction; glama's card had been frozen at v3.0.0 (2026-03-30) as a result.
- **Silent-SQLite-fallback integrity boundary.** The root `Dockerfile` now ships `CORTEX_RUNTIME=cowork` for zero-env DB-less operation — which made a dangerous case possible: a production user passing an unreachable `-e DATABASE_URL=…` would have silently landed on SQLite. `memory_store` now distinguishes an *explicit* `DATABASE_URL` (env-set) from the config default: explicit + unreachable → loud `explicit_database_url_unreachable` refusal (opt-out via `CORTEX_ALLOW_SQLITE_FALLBACK=1`); no explicit URL → sandbox fallback unchanged. Found and fixed along the way: `tool_error_handler._classify_error` was re-classifying the refusal into the generic `database_not_connected` setup guide because the message embeds raw psycopg error text — an explicit-marker guard now runs before the generic keyword scan.
- Root `Dockerfile`: CPU-only torch wheel pin (image 2.03 GB; the default index pulled the CUDA build), DB-less `HEALTHCHECK`, and `manifest.json`/doc tool-count drift corrected to the measured ground truth (49 standalone / 52 with upstream integrations).
- CodeQL `py/incomplete-url-substring-sanitization` alerts #97/#98 (false positives on `list[str]` membership asserts): the 5 sibling test sites hardened to exact-equality assertions; both alerts now read `fixed`.

### Added
- **Blocking `docker-smoke` CI gate** (`scripts/docker_smoke.sh` + job in `ci.yml`): builds the bare image, runs it with zero env vars and zero linked services, drives real MCP stdio (`initialize` + `tools/list`), and fails the pipeline under 49 tools. This is the feedback loop whose absence let the contract stay broken for two months — verified in both directions (PASS at 49; synthetic FAIL at a raised threshold).

### Docs
- `PRIVACY.md` rewritten truthfully per surface (SQLite default for `.mcpb`/Cowork/sandboxed launches; PostgreSQL via explicit `DATABASE_URL` for the Claude Code plugin) — verified same-day by an E2E `remember→recall` round-trip on the pure-SQLite path (PG unreachable, fresh HOME, cross-process persistence). README gains an explicit Claude Cowork zero-setup line, and its tagline now matches the repo's accountable-memory positioning.

### Note
- Pre-tag guard: LongMemEval-S MRR 0.9166 / R@10 0.982 (manifest `20260712T191146Z`, `git_sha d56c72ac`, `reranker_active: true`, `reranker_state: loaded`) — bit-identical to the 4.13.2 band, as expected: this release is import-timing, deployment, CI, and docs only, entirely outside the read path. Both gated floors PASS (MRR 0.9166 vs floor 0.914 +0.0026; R@10 0.982 vs floor 0.982 +0.0000).

## [4.13.2] - 2026-07-12

### Fixed
- **MCP tool schemas drifted from their handler signatures (#98).** Several `inputSchema` declarations in the tool registry no longer matched the parameters their handlers actually accept, so schema-aware clients could not pass valid arguments. `tool_registry_memory.py` restores `supersedes_id` + `write_class` on both `remember` variants; `tool_registry_wiki.py` restores `memory_ids` on `wiki_write`; `remember_schema.py`'s `source` enum regains `distillation`. A new `tests_py/handlers/test_tool_schema_parity.py` asserts wrapper↔handler parity so the drift cannot silently recur (the known sibling gaps — `is_global`/`initial_heat` on `remember`, `title`/`body`/`summary` on `wiki_write` — are explicitly whitelisted and tracked as a follow-up).
- **`checkpoint` output schema was unsatisfiable and mistyped (#99).** `action` was declared `required` in the `outputSchema` but only ever populated on failure paths, and `checkpoint_id` was typed `string` while the handler returns an integer. `checkpoint.py` removes `action` from `required` (and now populates it on success), and retypes `checkpoint_id` to `integer`. Covered by `tests_py/handlers/test_checkpoint_output_schema.py`.

### Note
- Pre-tag guard: LongMemEval-S MRR 0.9166 / R@10 0.982 (manifest `20260712T123142Z`, `reranker_active: true`, `reranker_state: loaded`) — bit-identical to the 4.13.1 reference band, as expected: #98/#99 touch only tool-schema declarations and the checkpoint output object, outside the read path. Both gated floors PASS (MRR 0.9166 vs floor 0.914 +0.0026; R@10 0.982 vs floor 0.982 +0.0000).

## [4.13.1] - 2026-07-12

### Fixed
- **Windows: SessionStart memory injection lost to a `UnicodeEncodeError` (#96).** Under a pipe (Claude Code's hook runner), CPython encoded hook stdout with the locale code page (cp1252), which cannot represent the `⟦rcpt:N⟧` injection-receipt marker — the entire SessionStart banner (anchors, hot memories, checkpoint, grooming line) was silently discarded on every Windows session, and `auto_recall`'s UserPromptSubmit injection was exposed the same way. `launcher.py::main()` now reconfigures stdout/stderr to UTF-8 (`errors="replace"`) before anything else — one choke point covering the MCP server, all 8 hooks, and both detached background workers. Repro validated by forcing `PYTHONIOENCODING=cp1252` through a pipe. Reported with an exact position-25 diagnosis and a validated A/B by @mbe14.
- **Windows: `_pip_install`'s commit destroyed shared dependency packages under a running server (#97).** The commit loop blindly `rmtree`'d + `os.replace`'d every resolved entry — including transitives like numpy whose `.pyd` files the concurrently-booting MCP server had locked — leaving husk packages, and the unconditional `finally: rmtree(tmp_dir)` destroyed the fresh copy too, making the failure permanent and re-triggering a multi-hundred-MB install per prompt. Fixed with all four measures from the report: a dist-info idempotence guard (satisfied entries are never touched), a rename-aside/rollback non-destructive commit that preserves `tmp_dir` on failure, a version-pinned success stamp + bounded directory lock taking the check out of the SessionStart hot path, and a dist-info presence probe (no more importing torch inside the hook). The bootstrap logic moved to a dedicated `scripts/launcher_deps.py` (stdlib-only preserved) with 21 tests including a simulated mid-commit `PermissionError` rollback. Reported with root cause and the fix list by @mbe14.

### Note
- Pre-tag guard: LongMemEval-S MRR 0.9166 / R@10 0.982 (manifest `20260712T021633Z`) — bit-identical to the reference band; the launcher is pure process bootstrap, outside the read path. Real-Windows confirmation (genuine file locks, genuine cp1252 console) pending from the reporter, as with #91–#95.

## [4.13.0] - 2026-07-11

### Added
- **Grooming becomes continuous instead of session-bound (G-2/G-3/G-4) — closes a measured 76-day wiki-silence gap.** The 4.12.0 program made memory *understand itself*; this release makes it *maintain itself* between sessions, not only during them. `run_wiki_maintenance` now runs a recurring citation-reconciliation pass (`wiki_citation_seed_pass`, 15–49ms, HIGH-reliability FK-verified pairs only — same classification logic as the 6.8 seed campaign, only the cadence changes, not the fabrication policy) and a `lesson_promotion` backlog count (0.8ms with a new `idx_memories_tags_gin` index, down from 81ms sequential scan) reported as its own field, deliberately not summed into `pending_total` (distinct queue, distinct consumer). `curate_distill`'s backlog was measured at 2.6s/pool and explicitly **not** wired into the periodic pass — at the measured 47 cycles/day cadence that would cost ~122s/day for a number nobody consumes without calling the tool directly; the decision and its evidence are documented in `wiki_backlog_pass.py`.
- **`get_grooming_health` (new READ_ONLY MCP tool, G-4).** On-demand aggregation (~1s) of backlog + staleness for wiki curation, distillation, and lesson promotion. `memory_stats` gains a cheap `grooming_staleness` field (~30ms, ages only, no backlog count — keeps the existing ~50ms→75ms latency contract). `session_start` prints a single line (never a header, never a paragraph) when any grooming type exceeds its staleness threshold — `GROOMING_STALENESS_THRESHOLD_DAYS = 6.0`, sourced from a real query against `consolidation_log` (p90 inter-cycle gap = 2.0 days over 19 active days, threshold = 3× p90, cited in `mcp_server/core/grooming_health.py`). Measured live before this release shipped: wiki backlog 12 (fresh), distillation backlog 25 (never run), lesson-promotion backlog 133 (never run) — the exact 76-day silence and multi-thousand-item backlog this program set out to make visible.
- **`scripts/groomer.py` — a scheduled session groomer (G-3).** Dry-run by default; `--apply` is gated behind the same `CORTEX_HEADLESS_AUTHORING=1` opt-in and budget caps the headless wiki worker already uses — no new privilege surface. A new `distill_drain` module lets a `claude -p` child call `remember()` itself over MCP using `curate_distill`'s existing prompt verbatim (skipped under `CORTEX_HEADLESS_AGENTS=0`/`--safe-mode`, which disables MCP). Invariant: no new memory *type* is ever auto-promoted without the existing per-type policy each was designed under (dedup/reheat exemptions preserved from 6.6/7.2). A `has_active_session_window` guard in `session_registry.py` avoids running the groomer while a live interactive session holds the same project. Scheduling itself is **not installed** — `scripts/com.cortex.scheduled-groomer.plist` and `docs/groomer-scheduling.md` (weekly cadence, justified against the measured session frequency) are shipped for the operator to install by hand; this release ships the mechanism, not the cron entry. Known scope gap, documented in `docs/groomer-scheduling.md`: the wiki staleness *signal* (curation-cluster backlog) is not yet the same queue as the wiki leg's actual drain queue (`headless_authoring`'s curation-gap/anchor scan) — left open for a future increment.

### Fixed
- **Headless wiki writes now go through the same governed path as interactive writes (G-1) — and a latent production bug is fixed on the way.** `page_io._rewrite_page`/`_write_anchor_page` previously wrote wiki pages with a raw `page_path.write_text()`: zero `write_class`, zero pointer memory, zero `wiki.citations` row, zero provenance grading. A single `wiki_write.write_governed_page()` is now the *only* function allowed to call `infrastructure.wiki_store.write_page` — both the interactive `wiki_write` MCP tool and the headless worker route through it exclusively; the old raw-write call sites are deleted, not shadowed. Headless writes get a `headless-authoring` tag (+`anchor` for new pages) for audit provenance; `write_class` stays `mechanical`, matching `write_governed_page`'s existing contract (the class describes the *pointer* write's nature, not who authored the underlying page). `CORTEX_HEADLESS_AUTHORING` stays opt-in default 0 — this release does not activate it.
- **CRITICAL — every interactively-authored wiki page has been silently failing its own database sync since the anchor-page template was written.** Root-caused while verifying G-1 against real PostgreSQL: the anchor-page frontmatter template hardcoded `status: living`, but `wiki.pages.status` has a `CHECK` constraint accepting only `seedling`/`budding`/`evergreen` — every insert with `status: living` raised a `CheckViolation`, silently swallowed by `_sync_page_and_cite`'s best-effort exception handler. This was invisible before this release because the raw-write path (now removed) never called `page_row_from_md`/`upsert_page` at all. The same literal string is used by `auto_curator.py`'s `WIKI_AUTHORING_PROMPT`/`WIKI_COVERAGE_PROMPT` templates that the *interactive* `curate_wiki` tool instructs the in-session LLM to use — meaning every interactively-authored `curate_wiki` page in production has been silently failing its `wiki.pages`/`wiki.citations` sync since that template's origin, consistent with this program's own measurement that `wiki.citations` was empty before the 2026-07-11 seed campaign. All 3 occurrences (`page_io.py` + 2× `auto_curator.py`) corrected to `seedling`. Flagged as worth a dedicated verification pass on whether the earlier seed campaign's citations went through a valid `status` or bypassed the sync path entirely.
- **Bench harness volume leak.** The ephemeral per-run PostgreSQL containers left anonymous `PGDATA` volumes behind on every run; 46 orphaned volumes (31.5 GB) had filled the Docker VM. `docker rm -f -v` now removes the container's volumes together with the container.
- Tool-count reconciliation: 49 standalone / 51 codebase-only / 52 full-upstream MCP tools (1 new: `get_grooming_health`).

### Note
- **Pre-tag guard (all three benchmarks, "×3"): LongMemEval-S MRR 0.9166 / R@10 0.982, LoCoMo MRR 0.8021 / R@10 0.9193, BEAM-100K MRR 0.5469 (not gated) — manifest `20260711T172056Z`, `reranker_active: true`, committed at `benchmarks/results/repro/20260711T172056Z/`. All 4 gated floors PASS, no regression against the 4.12.0 reading.**
- This release closes the "grooming continu" mandate: documentation and memory hygiene were previously something that improved only *during* an active session (headless worker, interactive `curate_wiki`) and silently regressed the other 76 days between sessions with zero visible signal. G-2/G-3/G-4 make the recurring maintenance mechanical and the backlog observable; G-3's scheduling artifact is deliberately left uninstalled pending the operator's own dry run.

## [4.12.0] - 2026-07-11

### Added
- **Provenance graded at write time (M-D5, 7.5).** Every `remember` call is now graded locally (`verified` / `verifiable` / `unverifiable`, zero network — URL checks stay unsampled at write time, the same "ceiling verifiable" semantics `validate_memory` already uses when its own `url_check_limit=0`) and surfaces as an additive `prov:<grade>` tag plus a transient `response["provenance"]` hint, reinforced when the write is both `unverifiable` and `write_class="deliberate"` (M-D2/7.4's durable-testimony class). New `grade_from_content()` in `validate_memory.py` reuses that module's existing local-I/O checks (path resolution, git-commit lookup, artifact digests) instead of reimplementing them — and, critically, `validate_memory` **remains the sole writer of `source_attribution`**: the design doc's literal instruction to persist the grade there was overridden on discovery that the column already carries a different, incompatible epistemic-origin vocabulary (`perceived`/`told`/`inferred`/`unknown`) that the confabulation guard (`recall_confabulation_risk`) keys off of — writing a grade value there would have silently and permanently disabled that guard on every fresh memory. A dry-run corpus sweep driver (`scripts/provenance_sweep.py`, reusing `validate_memory`'s own paginated handler, zero new grading logic) is committed: 11,012 memories, `unknown 7644 → verified 1997 / verifiable 3064 / unverifiable 5951` projected. **`--apply` deliberately not run** — 3,042 of 11,012 memories would newly flip `is_stale=true` (the pre-existing staleness/grading coupling), which the design's own acceptance criteria flags as requiring a G-ranks check before any live apply.
- **Lessons promoted to a first-class, traced object (M-D6, 7.6).** The `lesson`-tagged memory becomes the single canonical form (no new table) for what used to be four disjoint shapes (lesson memories, `memory_rules`, `prospective_memories`, `procedural_skills`); rules and triggers gain a nullable `source_memory_id` pointer back to the lesson that produced them (additive migration, PG + SQLite parity), and a new READ_ONLY `lesson_promotion` MCP tool proposes promotion jobs (rule / trigger / wiki) without ever calling `add_rule`/`create_trigger`/`wiki_write` itself — enforced by a test that greps the handler source for those names, mirroring `curate_wiki`'s server-proposes/LLM-executes architecture. Session-end self-critique suggestions that were previously computed and discarded are now persisted as `lesson-candidate` memories (`write_class="deliberate"`, best-effort, never fails session-end). A full round-trip test proves the loop on real PostgreSQL: `remember(lesson)` → `lesson_promotion` surfaces a job → `add_rule(source_memory_id=...)` → `apply_rules` (the actual recall-time function) measurably differs with the rule present → the lesson is superseded and drops out of future batches.
- **Understanding-level distillation (M-D8, 7.8) — closes the "mémoire qui comprend" program.** New READ_ONLY `curate_distill` tool assembles three kinds of dossiers for the in-session LLM to turn into `lesson` memories (`write_class="deliberate"`): error→success pairs (entity-overlap, self-pairing guarded), temporal co-access clusters, and entity-family clusters (capped at 12 members — an unbounded 53-member cluster was found live on the dev corpus). Idempotent via a `distill-of:<hash(sorted_ids)>` marker, same skip-before-offer pattern as `memify_derive`. Dry-run against the real dev corpus (11,012 memories, read-only, verified zero rows written) found 25 eligible dossiers (10 error→success, 3 co-access, 12 entity-family) and, along the way, two real bugs invisible to synthetic-fixture unit tests: a memory tagged both `error` and `success` pairing with itself, and a falsy-zero `or`-default bug silently overriding an explicit `min_avg_heat=0.0`.
- **Wiki citation seed campaign (M-D7, 7.7).** A reliability audit of three candidate memory↔wiki-page link sources found only one usable at HIGH confidence: `wiki.pages.memory_id` (20 of 154 pages, a real unique FK to `memories`). The other two are either an exact duplicate of those same 20 pairs or, for `wiki.page_sources` (559 rows), the wrong entity type entirely — it links pages to source files, has no `memory_id` column, and using it would mean fabricating a path→memory join the project already refused in 6.8/Q5. A one-shot seed script (`scripts/wiki_citation_seed.py`, mirrors the `memory_reheat.py` core/infra/handler/script split) is committed dry-run only: `scanned=20, would_seed=20, already_cited=0` — deliberately no automatic retroactive backfill, matching the 6.8/Q5 precedent.
- Tool-count reconciliation: 48 standalone / 50 codebase-only / 51 full-upstream MCP tools (2 new: `lesson_promotion`, `curate_distill`).

### Note
- **The "mémoire qui comprend" program is complete** — all five identified gaps (G1–G5: provenance at write, explicit write-class, per-class homeostatic fold, lessons as first-class objects, understanding-level distillation) are now addressed across this and the preceding releases.
- Pre-tag guard (all three benchmarks, "×3"): LongMemEval-S MRR 0.9168 / R@10 0.984, LoCoMo MRR 0.8024 / R@10 0.9183, BEAM-100K MRR 0.5455 (not gated) — manifest `20260711T115601Z`, `reranker_active: true`, committed at `benchmarks/results/repro/20260711T115601Z/`. All floors PASS (LongMemEval and LoCoMo both sit slightly above their published reference), no regression.
- **Operator applies still pending, not run by this release** (per task mandate, orchestrator decides): the provenance sweep's `--apply` (blocked on a G-ranks check for the 3,042 projected staleness flips), the wiki-citation-seed campaign's `--apply` (20 candidate rows), and a re-heat re-measure for the deliberate-memory population (scheduled from the 6.6/7.2 campaigns, unaffected by this release).

## [4.11.0] - 2026-07-11

### Added
- **Graph channel resurrected + domain-scoped, tail-fill by default (ADR-0054).** `spread_activation_memories` had been dead since its introduction: a non-recursive `WITH` clause raised a SQL error on every call, swallowed by a bare `except Exception` — invisible because the unit tests mocked the DB layer, so the channel never once fired against real data in production. It is now repaired, scoped to the recalling memory's domain (cross-domain spread is opt-in), and defaults to **tail-fill**: the graph only completes recall slots left short after re-ranking (recalls already at `k` are never touched, never reordered). This is the channel's first empirical measurement in `augment` mode — MRR −0.016 / R@10 +0.002 — which under the project's zero-regression bench gate is why `tail` (not `augment`) ships as the default; both modes plus `off` are exposed as `sa_mode` on the MCP `recall` contract. Collateral fix: `recall_memories` returned a raw `datetime` for `created_at` in violation of its own documented schema; both readers now normalize to ISO-8601, and the candidate contract is under test.
- **Explicit `write_class` at the `remember` contract (M-D2, 7.4).** `write_class` (`auto` / `deliberate` / `derived` / `mechanical`) is now a validated parameter on `remember`; all 17 internal writers declare their class explicitly instead of it being inferred from `source` strings. New `memories.write_class` column (additive migration + one-shot backfill, `scripts/backfill_write_class.py`); the homeostatic fold (4.10.0) reads it directly, closing the inference gap that caused the 7.2 finding below.

### Fixed
- **219 silent excepts audited, 30 critical sites repaired.** Full audit at `docs/audits/silent-except-audit-2026-07-11.md`; the 30 fixes on the recall / write-gate / consolidation paths route through a new `observability/silent_failure.py` module so degraded-but-not-crashed states are logged and queryable instead of disappearing — the same failure shape that hid the dead graph channel above. 36 `caplog`-based tests pin the new behavior.
- **Re-heat source taxonomy was comparing the wrong strings since its origin.** The non-deliberate source list in the 6.6 re-heat campaign compared against values like `"seed"` where the real column held `"seed_project"` — the filter never excluded anything it was meant to. Centralized in `write_class.py`; a closed-world test now pins all 95 real source values. Measured impact: 91 of the 540 memories raised by the 6.6 campaign were mechanical, not deliberate (`docs/campaigns/reheat-controle-7.2-dryrun.md`, dry-run/read-only). Five bench harnesses gained `require_reranker=True`.

### Note
- Pre-tag guard: LongMemEval-S MRR 0.9166 / R@10 0.982, LoCoMo MRR 0.8014 / R@10 0.9157, BEAM-100K MRR 0.5493 (not gated) — manifest `20260711T080344Z`, `reranker_active: true`, committed at `benchmarks/results/repro/20260711T080344Z/`. LoCoMo is the first measurement taken on the repaired bench instrument (4.10.0's container-isolation + reranker-cache fixes); 0.8014 sits inside the gate's tolerance (Δ −0.0036 against the 0.805 reference, tolerance 0.005) — reported honestly as a first clean-instrument reading, not re-litigated as a regression.

## [4.10.0] - 2026-07-11

### Fixed
- **CRITICAL — FlashRank reranker silently disabled by `/tmp` cache purge.** `_ensure_reranker()` instantiated `flashrank.Ranker` without a `cache_dir`, falling back to the library default (`/tmp`) — macOS purges `/tmp`, and the resulting `NoSuchFile` was swallowed by a bare `except Exception`, permanently disabling production re-ranking for the rest of the process with zero log signal. Six LongMemEval runs were reported under this silently broken instrument (MRR 0.9163 → 0.8636, measured Δ −0.053; R@10 nearly untouched). Fix: durable `cache_dir` (`~/.cache/flashrank`, honoring `$XDG_CACHE_HOME`), a first-failure warning log naming the searched path and exception, and new externally-consumable state (`RerankerStatus`, `ensure_reranker_loaded()`, `reranker_status()`, `model_sha256()`). The three floor-gated production-parity bench harnesses (LongMemEval/LoCoMo/BEAM) now fail fast via `BenchmarkDB(require_reranker=True)` instead of silently scoring a first-stage-only pipeline as production-equivalent; `MANIFEST.json` records `reranker_active`/`state`/`model_sha256`; the ephemeral bench PG container gains `--shm-size=1g` (source: pgvector README "Indexing" — parallel HNSW builds need shared memory), closing a co-occurring `REINDEX` `DiskFull` failure mode from the same incident. **Existing installs silently lose their re-ranker on every `/tmp` purge — upgrade recommended.**
- **Bench measurement instrument repaired: cross-worktree container contamination.** `start_db()` used a fixed container name (`cortex-bench-pg`) and fixed port (55432) shared across every worktree checkout; two concurrent `make longmemeval` runs from different worktrees silently cross-contaminated each other's scores with no visible error (measured: 0.9163 isolated vs. 0.78–0.86 under concurrency — invalidating 4+ prior benchmark runs and nearly causing a valid increment to be reverted). Every run now gets its own container (`cortex-bench-pg-<pid>-<hex>`) and its own kernel-assigned port, plus a best-effort orphan sweep for containers whose owning PID is dead.
- **Homeostatic fold no longer re-suppresses deliberate memories (M-D3, 7.1).** The class-blind fold re-suppressed the deliberate write class within hours of the 6.6 re-heat campaign (deliberate median `heat_base` collapsed 0.25 → 0.1346 same-day, instead of the planned J+30 re-measure). Health is now measured AND folded per write class (new `write_class.py` — single classification choke point: auto/deliberate/derived/mechanical) instead of one aggregate mean across a 92%-auto corpus applied to every row; only the `auto` class is regulated (the Turrigiano/Tetzlaff homeostatic-plasticity population assumptions don't hold for the other three, documented per-class). `homeostatic_state`'s PK becomes `(domain, write_class)` (additive one-shot migration, legacy rows relabeled `auto`); a new `homeostatic_fold_log` table journals every fold event.

### Added
- **Novelty-only template normalization for auto-captures (M-D1, pivoted).** The auto-capture template and the memify-derive relationship sentence drove cosine similarity to 0.95–0.99 between distinct facts, flattening structural novelty for the 92%-auto-capture traffic class. `capture_template_normalize` now feeds ONLY the write gate's novelty decision (`compute_template_normalized_similarities` re-scores the top-5 HNSW candidates on template-normalized text purely for the discarded `emb_nov` signal); the stored `embedding` column and the recall path are untouched (grep-verified: zero remaining callers touch the `embedding` column or any stored vector). Scope was narrowed from an earlier design that also normalized stored embeddings — three LongMemEval runs on that path showed a consistent MRR regression whose root cause could not be conclusively isolated from the bench-container concurrency hole fixed above; abandoned under the zero-tolerance bench gate rather than negotiated.
- Bench harness now pins the embedding model revision (`sentence-transformers/all-MiniLM-L6-v2`) and records it plus the `torch` version in `MANIFEST.json` — the local HF cache held two snapshots with `refs/main` moving between them; confirmed not the cause of the reranker regression above, but an unbounded future risk closed pre-emptively.

### Note
- This release is dominated by measurement-instrument fixes: the reranker cache bug, the bench container isolation bug, and the embedding-revision pinning all exist because `benchmarks/reproduce.sh` itself was compromised or under-specified. No scoring/gate behavior changed except becoming honest about failures that were previously silent.
- Pre-tag guard: LongMemEval-S MRR 0.9166 / R@10 0.982 (manifest `20260711T035233Z`, `reranker_active: true`, elapsed 1663s) — sealed on the exact release tree with the durable reranker cache and an empty `/tmp`, revalidating the historical `[0.9163, 0.9166]` band as the full-pipeline reference. The 0.8636 readings of 2026-07-10/11 were the broken instrument (reranker silently absent), not a code regression.

## [4.9.1] - 2026-07-10

### Fixed
- **Homeostatic cycle labels the real dominant domain again (Phase-4 regression).** Since the streaming optimization (`84cfdedf`), the scalar path computed its health factor from an always-empty domain list and wrote it to `domain=''` on every consolidate cycle — the mechanism was effectively inert in production. Domain counts are now accumulated in the same cursor pass as the Welford moments (no extra I/O), the selection rule is shared between streaming and materializing paths, and the polluted `''` row is purged (absence falls back to the documented neutral factor). Known honest limit, deliberately unchanged: the cycle corrects the most *populated* domain, not the least *healthy* one.
- **CI back to green.** The near-dup member-stats test no longer predicts the homeostatic factor (it probes it), `homeostatic_state` joined the test-isolation cleanup list — the leak that made two suites flaky across processes — and the I6-D5 re-heat writer is whitelisted in the I2 heat-writer invariant with a formal justification (ADR-0053: routing through the canonical writer would have broken the CAS guard and the decay clock needed by the J+30 re-measure).

### Changed
- Marketplace manifest versions realigned (cortex 4.9.0→current, cortex-viz 2.4.0→2.5.0) — the cross-plugin interdependency file had drifted.

### Note
- Pre-tag guard: LongMemEval-S MRR 0.9163 / R@10 0.982 (manifest `20260710T185055Z`) — within the equivalence band `[0.9163, 0.9166]` proven by the v4.9.0 twin-run + control arbitration.

## [4.9.0] - 2026-07-10

### Added
- **Graded provenance verifier (I6-D6).** `validate_memory` now grades every memory `verified / verifiable / unverifiable` (worst-case across its references: file paths + wired `changed_paths`, git commits via the hardened subprocess helper, URLs capped at *verifiable* and excluded from the staleness score, artifact digests recomputed, DOI/arXiv recognized) and is the sole writer of `source_attribution` — the C1 epistemic classification (Johnson 1993) is preserved at initial write and overwritten by verification passes. De-stale and pagination included; a `threshold=0.0` de-stale blocker was found and fixed en route.
- **Flow-forward memory→wiki citations (I6-D7).** `wiki_write` — the real executor of curation jobs — records one deduplicated citation per memory actually used (partial unique index on `(page_id, memory_id)`; unqualified `ON CONFLICT` lets Postgres pick the applicable index per row), feeding the brain graph's DOCUMENTS edges. `curate_wiki(report_uncited_deliberate=true)` reports important memories still lacking a page. No retroactive backfill for existing pages (reversible default).
- **One-shot deliberate-memory re-heat (I6-D5).** 544 deliberate memories raised to `effective_heat ≥ 0.25` (the measured top-10 cliff bound) by probing the real PL/pgSQL decay function — never lowering anyone, 7 structurally unreachable left intact. Median deliberate heat 0.14 → 0.25; rank protocol: 5/5 improved-or-stable, 4/5 at rank 1. Re-measure scheduled 2026-08-09.
- **Exact-duplicate collapse (I6-D1).** 91 exact duplicates (55 groups, re-measured) superseded via CAS batch toward the hottest survivor — append-only, metadata untouched, zero duplicate groups remain among current memories.

### Changed
- **Near-duplicate auto-collapse: measured NO-GO (I6-D2).** Calibration on 100 audited labeled pairs shows no cosine threshold reaches 100% precision (0.95–1.00 stratum: 10%) — auto-capture templating pushes similarity to 0.99 between genuinely distinct facts. Per the campaign gate: zero auto-supersession; 35,869 candidate pairs filed for review; calibration tooling committed for future re-runs.
- **Read-path source down-weighting (6.7): NOT triggered.** The suppression class that motivated it is eliminated by the corpus levers alone (see re-heat ranks); the residual case is content-generic lexical competition, deferred to the benchmark-neutral template-normalization lead.

### Note
- Pre-tag guard with variance arbitration: candidate tree measured MRR 0.9163 twice (R@10 0.982); a same-day control run on the v4.8.0 tree also measured 0.9163 — equivalence proven, the earlier 0.9166 being the top of the observed identical-code band. Manifests `20260710T152643Z`, `20260710T155614Z` and `20260710T162510Z-control-v480` committed.

## [4.8.0] - 2026-07-10

### Added
- **`explore_features` attribution mode traces real sessions.** It had returned an empty graph in production since inception (`trace_attribution` was only ever called with no conversations). It now feeds on project-scoped conversation discovery (`discover_conversations_for_projects`, bounded to 20 samples — measured ~12 ms vs ~270 ms for an unscoped scan), producing a real decision-attribution graph from the machine's own session history.

### Fixed
- **Cross-process test-DB contention eliminated.** The shared `cortex_test` database plus each process's unconditional cleanup fixture meant two concurrent pytest runs (trivial with many worktrees) corrupted each other — the true root cause behind every "flaky" `test_store_consolidate_recall` / `test_validate_memory` report (order-dependence and embeddings-backend hypotheses refuted by deterministic reproduction). Each local pytest process now creates its own throwaway PG database, dropped at session end, with opportunistic sweeping of databases leaked by SIGTERM'd runs. CI and explicit `CORTEX_TEST_DATABASE_URL` overrides unchanged.
- **`AttributionNode.activation` no longer mixes floats and strings.** Three classifier nodes copied categorical `CognitiveStyle` values verbatim into a numeric field; classification now lives in a dedicated `categoricalValue` field and `activation` is always a float (0.0 when no legitimate magnitude exists — no fabricated numbers).

### Changed
- **Interpretability boundary typed.** `explore_features` and its core modules (persona vector, attribution tracer, behavioral crosscoder, sparse dictionary) exchange Pydantic models (`shared/types_features.py`) instead of untyped dicts, with validation regimes matching each type's real provenance (JS-compatible round-trip vs in-memory). Serialized responses proven byte-identical before the attribution fixes above.

### Note
- Pre-tag non-regression guard (first full application of the bench-before-release procedure): LongMemEval-S MRR 0.9166 / R@10 0.982 on the frozen release tree (manifest `20260710T132409Z`) — identical to the campaign reference.

## [4.7.0] - 2026-07-10

### Added
- **memify now actually extracts derivable facts.** `identify_derivable_facts` (defined, tested, never called since inception) is wired into the memify cycle: strong entity relationships become append-only derived memories with tag provenance (`derived`, `derived-rel:<key>` idempotence key, `derived-src:<id>` pointers). The write gate is never bypassed — gate rejections are valid outcomes. Bounded per run (measured).
- **Memory domain backfill (internal evidence only).** Domainless memories are reattached from their own `directory_context` (24) — and, after the linked-worktree fix below, 296 more; the remainder is explicitly tagged `domain-orphan` rather than guessed. Idempotent, never overwrites, campaign artifacts committed.
- **Linked git worktrees resolve to their parent project's domain.** Pure-Python `gitdir:` dereference at the single resolve choke point — no subprocess, fail-safe, no duplicate domains.

### Fixed
- **Memory-to-memory links were never written.** Both link sites (CLS semantic→episodic provenance, near-duplicate "link" curation) passed memory ids into entity-FK columns and swallowed the FK violation with `except: pass` — since their introduction. Links are now written as provenance tags (same mechanism as memify derivation); no silent exception swallowing survives on this path.
- **Checkpoint/session-log writers use the canonical transcript-stem session identity** (event `session_id` diverges on resume/clear); explicit caller-provided ids are preserved.
- **Tool descriptions/annotations aligned with what the code does** — detect_gaps (4 real axes), assess_coverage (no file coverage), validate_memory (file paths only), backfill_memories (file-level idempotence only), and READ_ONLY corrected to non-idempotent-write on navigate_memory, recall, recall_hierarchical and drill_down (they mutate replay counters on every call). A table-driven anti-drift guard test now fails on reintroduced false promises.
- **Dead code removed with per-item proof chains**: the scanner's never-consumed `session_id` output field (and its `fallback_id` helper), and the entire `shared/types.py` scaffolding module (14 Pydantic models, zero references since their initial commit).

### Changed
- **Recall receipt path: 6.8 ms → 0.07 ms.** The parent-process start signature is memoized for the server's lifetime (correctness proof: POSIX orphan reparenting makes `getppid()` change at most once); the session id itself is never cached.
- Unsourced heat constants now say so at their sites (§8 honesty): the wiki citation bump, the reconsolidation bump (its previous label pointed at a calibration document that does not calibrate it), the Hebbian entity bump, and the wiki lifecycle thresholds. Values unchanged; a pre-registered calibration sweep is the documented exit path.

### Note
- The `readOnlyHint` corrections on high-volume recall tools may affect MCP client auto-approval behaviour; if confirmation friction appears, the revert lever is commit `efe5dedf` — the underlying writes existed all along.
- Non-regression guard: LongMemEval-S MRR 0.9166 / R@10 0.982 (manifests `20260710T082114Z`, `20260710T102406Z` committed) — identical to the pre-campaign reference.

## [4.6.0] - 2026-07-10

### Added
- **Session identity channel — T2 completion (blame path, decision 4255039).** A per-window session registry (`~/.cache/cortex/session-registry/<claude_pid>.json`) is written by the hooks (SessionStart writes + purges dead entries, each prompt refreshes, SessionEnd tombstones) and read by MCP handlers through validated pid lineage (opaque start-time token defeats pid reuse). `recall`'s T1 injection receipts now carry the canonical session id (transcript stem); every uncertain case — headless, legacy hooks, dead window, tombstone — degrades to NULL, never a stale value.
- **Wiki citations write-path (unblocks CITED_IN edges).** A successful `wiki_read` now records one deduplicated citation per (page, session) — partial unique index on `wiki.citations(page_id, session_id)` + `ON CONFLICT DO NOTHING` — so the heat bump cannot repeat within a session, and `wiki.citations.session_id` finally feeds the CITED_IN wiki→discussion edges in the cortex-viz brain graph. No resolved session → no citation.

### Changed
- `wiki_read` is no longer strictly read-only: the page read stays filesystem-only, but a successful read records a citation as an explicit, best-effort observability side effect (a citation failure never fails the read). Docstring and MCP annotations updated accordingly.

### Fixed
- **Windows: profile domain detection defeated by casing (#95).** `cwd_to_project_id` lowercases ids while profiles keep original casing; comparisons are now case-folded through a single `normalize_project_id` at all four affected sites — including `record_session_end._resolve_domain`, the site that silently stored memories with `domain: ""`. Reported with a validated patch by @mbe14.

## [4.5.0] - 2026-07-10

### Added
- **Document content indexing (D6).** `ingest_codebase` gains a docs pass (`ingest_docs` flag, default on): the content of discovered `.md`/`.markdown`/`.mdx` files becomes recallable memories (tags `doc`, `src:ap`, project domain), and AP's Markdown-link edges are projected as `references` relations — idempotent by construction. Per-file bound of 1 MiB reused verbatim from AP's `MAX_PARSE_BYTES` (`indexer/mod.rs:48`), cross-checked against real corpora.
- **Ingestion provenance (D5, ADR-0052 §2).** The primary path (`ingest_codebase`) tags what it writes with `src:ap` + `src:ap-version:<resolved>`; the fallback path (`codebase_analyze`) tags `src:native` and reports an explicit `fallback_status` — `src:native-fallback` when AP is unreachable, `src:native-precedence-violation` (with an ADR-0052 warning log) when it is not. A version-parity guard compares the two AP client paths (`ap_bridge` vs `mcp_client_pool`) and surfaces `match`/`mismatch`/`unknown` in the analyze stats.

### Fixed
- **Windows: domain registry fast-path (#93).** Registry keys are now normalized to forward slashes at the single construction choke point — the fast-path dict lookup works on Windows instead of silently falling back to slower matching.
- **Windows: post-timeout `communicate()` trap (#94).** New shared `subprocess_safe.run_with_hard_timeout` (kill-without-recollect pattern) now backs the two high-risk git call sites reachable from live handlers (`record_session_end`'s commit-window scan, graph diff execution).

## [4.4.0] - 2026-07-10

### Added
- **`ingest_findings` MCP tool (ADR-0052).** Cortex consumer of automatised-pipeline findings artifacts (`runs/<run_id>/`): a verified finding (stage-2) becomes a wiki page (`reference/findings/<slug>`) + a re-verifiable decision memo in `wiki.memos` — dual anchoring: sha256 of the raw artifact bytes plus AP's own `transcript_digest` copied verbatim (never recomputed) — + a protected memory; an unverified finding becomes a low-confidence `hypothesis` memory only, never a page. Page↔file anchoring via `wiki.page_sources`: `link_kind='finding'` for code files (stage-4 matched symbols) and `link_kind='extracted_from'` for the source document the finding was extracted from (stage-1 `source_path`). Idempotent by construction (re-ingesting a run duplicates nothing).
- **ADR-0052** — AP↔Cortex flow direction (Cortex pulls from disk; AP stays file-only), ingestion precedence (`ingest_codebase` primary, `codebase_analyze` explicit fallback), and the `ap_bridge.py` duplication debt with its repayment condition.

### Fixed
- **Memory rules drift.** `add_rule` now validates against the grammar the engine actually parses (`validate_rule` wired, write-time fail-closed rejection); hard `filter` rules now EXCLUDE matching memories instead of keeping them (semantic inversion); unparseable legacy conditions are fail-safe (match nothing, logged) instead of fail-open.
- **Windows: `remember` hangs indefinitely (#91).** `_git_root`/`_get_remote_url` replaced with pure-Python lookups (walk up to `.git` dir/worktree file; parse `.git/config`) — no subprocess, no pipes, so the post-timeout `communicate()` handle-inheritance trap is gone by construction. Reported, diagnosed and fix validated by @mbe14.
- **Windows: first `remember` deadlocks on lazy scipy/sklearn import (#92).** Eager import on the main thread at server startup, before the event loop (~1.6 s cold, once per process). Reported and fix validated by @mbe14.
- Tool-count test assertions updated for the new standalone tool (45→46).

### Changed
- `wiki.page_sources` CHECK constraints extended additively (`link_kind`: `finding`, `extracted_from`; `source`: `ap-pipeline`), with idempotent migration for existing databases.

### Note
- Version realignment: the 4.3.0 release bumped only `plugin.json` (pyproject stayed at 4.2.0, no changelog entry — added retroactively below). 4.4.0 realigns pyproject, plugin manifest and changelog.

## [4.3.0] - 2026-07-09

### Added
- Wiki domain backfill: real project domain resolution for catch-all wiki pages (PR #90).

## [4.2.0] - 2026-07-08

### Added
- **Wiki page→source-file linkage (ADR-0051, STEPS 1–4).** Every wiki page's primary documents now trace to a real file in the codebase via explicit provenance (claim_evidence > codebase_grounding > body audit trail), not fabricated synthetic links: schema surface for the linkage, writer-side persistence, a backfill pass for pages lacking frontmatter, and `references` link_kind persistence. This is the backend that cortex-viz 2.4.0 renders as wiki→file edges in the brain view.
- **CLS-B hippocampal replay tracking** with a soft non-regression gate C for consolidation.

### Changed
- `pg_store_wiki.py` split under the 300-line rule into focused modules.

## [4.1.0] - 2026-07-07

### Added
- Read-path supersession: superseded memory versions are excluded from recall via a `current_memories` view, so a knowledge update ranks and returns above what it replaced.
- Injection receipts / blame path (tranches 1–3): a `why` resolution traces each injected memory back through `⟦rcpt:N⟧` receipts to its hook channel and decision.

### Fixed
- PostgreSQL read path adapted to the pgvector 0.5.0 `Vector` loader.

### Changed
- Banner and diagrams restyled to the AI Architect design system; ruff pinned to 0.15.20.

## [3.25.0] - 2026-07-01

Headless wiki-authoring hardened end-to-end (subscription billing, full zetetic
agent roster, anti-recursion guard) plus the active-forgetting memory module and
Windows portability fixes.

### Added
- **Active forgetting (Module #6).** `core/active_forgetting.py` +
  `handlers/consolidation/forgetting.py`: two independent Drosophila dopaminergic
  forgetting circuits — permanent Rac1 trace erosion (chronic interference ×
  stage vulnerability) and transient DAMB retrieval block (Davis & Zhong 2017,
  Sabandal et al. 2021). Shipped with a falsification harness left failing where
  the model genuinely diverges from biology. (#69)
- **Safe headless wiki-authoring drain.** Async `claude -p` invocation
  (`asyncio.create_subprocess_exec` + `wait_for`) that no longer blocks the event
  loop; per-cycle concurrency / wall-clock / USD budget via `CORTEX_HEADLESS_*`
  knobs (defaults 4 / 300s / $5); anti-fabrication `Scope.groundable` filter so
  non-derivable scopes (prd/decisions/changelog/roadmap/accessibility/
  localization) are never authored from scratch. (#70)
- **Full zetetic agent roster for wiki authoring.** Two-mode argv
  (`claude_cli._build_argv`, gated on `CORTEX_HEADLESS_AGENTS`, default on):
  agents mode loads the user roster only (`--setting-sources user`, project/local
  excluded so a malicious repo cannot inject settings/hooks) with a hard
  `--disallowedTools Write,Edit,Bash,NotebookEdit` deny ceiling that propagates to
  delegated subagents; solo mode falls back to `--safe-mode`. New
  `hooks/_headless_guard.py` no-ops every Cortex hook under
  `CORTEX_HEADLESS_AUTHORING_CHILD=1`, stopping consolidation→authoring recursion
  and memory pollution. (#72)

### Fixed
- **Windows cross-platform portability.** macOS/Linux compatibility preserved. (#68)
- **Headless drain billing.** The drain now uses a logged-in Claude subscription
  by default with API billing as explicit opt-in; previously `--bare` forced
  `ANTHROPIC_API_KEY` and the fail-closed guard skipped the whole drain on
  subscription-only machines. (#71)
- **Silent drain failure since 3.24 (root cause).** The variadic `--add-dir`
  swallowed the trailing positional prompt, so every drain with a `source_root`
  failed silently; the prompt is now passed via STDIN. (#72)

### Changed
- Bump `pydantic-settings` 2.14.0 → 2.14.2 (upstream security patch:
  `NestedSecretsSettingsSource` no longer follows symlinks outside
  `secrets_dir`). (#67)

## [3.24.1] - 2026-06-23

Cross-backend `recall` fix — PostgreSQL users could not use `recall`.

### Fixed
- **`recall` (and every read tool) on PostgreSQL.** The PostgreSQL store returns
  `numpy.float32` scores and `datetime` timestamps where the SQLite store returns
  `float`/`str`. FastMCP can only build `structuredContent` from JSON-native
  values, so a non-native field silently dropped `structuredContent` and the
  Claude Code host rejected the call with *"outputSchema defined but no structured
  output returned"* — on PostgreSQL only, while SQLite-backed tests stayed green.
  Added `mcp_server/shared/json_native.py::to_json_native`, applied at the
  `tool_error_handler.safe_handler` boundary every tool crosses, normalizing
  results to one JSON-native shape regardless of backend.

### Added
- Mutation testing (mutmut): `[tool.mutmut]` config + `scripts/mutation_check.sh`
  scoped per-change runner. Mandated on changed code by coding-standards §12.

## [3.23.0] - 2026-06-17

Registry-indexer build fix. No runtime behaviour change.

### Fixed
- **Glama (and any `uv run`-based registry indexer) build.** Added the
  `neuro-cortex-memory` console script (`[project.scripts]`, entry point
  `mcp_server.__main__:main`). Glama does not use the repo `Dockerfile`; it builds
  with `uv sync` and launches the server via `uv run neuro-cortex-memory`. Only
  `cortex-doctor` was declared, so `uv run neuro-cortex-memory` failed with
  `Failed to spawn: neuro-cortex-memory — No such file or directory`; the container
  exited before the MCP handshake, no tool registered, and the tools score
  collapsed. The new entry point starts the stdio server (equivalent to
  `python -m mcp_server`) and registers all 46 MCP tools at import time **without a
  PostgreSQL connection**, so `tools/list` answers inside Glama's DB-less container.
  The marketplace install path (`scripts/launcher.py`) is unaffected.

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
- `docs/provenance/pyright-remediation-plan.md` — phased plan to clear the 566 pyright errors.

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
  `docs/benchmarks/e1-v3-results.md`.
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
  Writeup: `docs/benchmarks/e1-v3-locomo-results-post-fix.md`. The pre-fix sweep is
  preserved at `docs/benchmarks/e1-v3-locomo-results.md`.
- **Phase A + B blend-weight calibration.** Central composite design + 5×5
  grid search; all six post-WRRF rerank constants confirmed near-optimum at
  the engineering defaults shipped today. `docs/provenance/blend-weight-calibration.md`.
- **Per-category delta analysis (LME-S).** Mechanism specialization
  surfaced: HDC specializes for multi-session reasoning, HOPFIELD for
  knowledge updates, ADAPTIVE_DECAY against stable preferences.
  `docs/benchmarks/e1-v3-per-category.md`.

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
