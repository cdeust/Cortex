Warning: truncated output (original token count: 78611)
Total output lines: 2802

# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed

- The former Claude repair actions are removed following the owner decision.
  Automatic Claude review remains review-only; owner mentions retain the
  separate implementation workflow described below and in ADR-1117.
- Duplicate legacy CI workflows are retired. Pipeline, required CodeQL and the
  protected merge resolver remain active.

### Fixed

- Exact remember replays return the existing id within the same write scope;
  explicit corrections still post supersession edges. Consolidation retains
  and supersedes legacy copies, preserves protection flags, and excludes
  benchmark rows and block replicas (#707). The new counter is
  `exact_duplicates.superseded_total`. SQLite writers need no registered `md5()`.
  Replays refresh source hashes without resetting heat, and identical deliberate
  batch items are refused before curation. Hard forget erases retained exact twins.

- Owner @claude mentions inherit the official action's tag-mode workspace edit
  approval instead of overriding it with auto mode (#822). Requests on the same
  thread run one at a time with up to 100 pending requests retained; automatic
  reviews keep their separate permission mode.

- The managed PostgreSQL server starts on Ubuntu 25.10 and 26.04, which ship
  no `libxml2.so.2`: Linux GNU now runs theseus 18.6.1, which bundles its
  runtime libraries (about 40 MB instead of 12 MB); macOS keeps 18.6.0. The
  published pgvector 0.8.7 archives load into it unchanged. 18.6.1 needs
  glibc 2.36, so Ubuntu 22.04 and RHEL 9 no longer get the managed server:
  Setup refuses them before the download, a new store stays on SQLite with
  that reason shown, a store already on it makes Setup fail with that cause
  (ADR-1114, owner decision 2026-10-28;
  Pipeline run 40649407965 failed on an ubuntu-latest runner on 26.04).
- Session registry POSIX `ps` probes report nonzero exits and invalid UTF-8
  as named errors with the command and stderr; hooks log the actual cause
  without starting a legacy consolidate worker (#682).

- Share the launcher's first-launch backend policy with wheel hooks and direct
  MCP startup: a fresh unconfigured HOME records SQLite before settings bind;
  explicit URLs and managed PostgreSQL keep their existing precedence (#703, #704).
- Stop installing the optional code-intelligence server during hook discovery;
  installation remains in explicit `scripts/setup.sh` and is disclosed in
  `PRIVACY.md` (#705).

- The `merge` job of `.github/workflows/pipeline.yml` sets `GH_REPO: ${{ github.repository }}` on its `gh pr merge` step: the job runs without a checkout, so gh could not infer the repository and failed with `fatal: not a git repository` after every stage was green (session-optimizer #65, run 39756969927, 2026-10-22).

- CI requires completed native Codex code and security reviews on the current
  head. Unresolved findings block protected integration. Partial reruns retain
  successful prerequisites and supersede obsolete skipped matrix placeholders.

### Added

- Claude PR reviews use Anthropic's official direct PR workflow and its five
  upstream reviewer agents (ADR-1117). Reviewer configuration loads from trusted
  main; PR content is read through GitHub. This replaces ADR-1116's custom
  workflow_run marker protocol. Codex retains its native review checks.
  Evidence: `docs/verification/claude-bot-ci-20261027.md`.

- **The single CI pipeline, run by the Claude bot (ADR-1115).**
  `.github/workflows/pipeline.yml` runs contract, unit (the SQLite-backed
  pytest suite, 90 % of lines from `coverage.xml`), regression
  (`tests_py/integration`), e2e (`scripts/docker_smoke.sh`), environment
  (`cortex-doctor` after a `pip install .` into a fresh venv on ubuntu, macOS
  and Windows, bare runner plus the pinned Claude Code CLI 2.1.296) and
  install (`scripts/install_e2e/run.py` on the three OS, the Windows leg new),
  then the bot's review and fix, then a squash auto-merge that fails
  explicitly instead of skipping; the release tag on push to main keeps
  ADR-0802's gate with `canonical_version`. The commands live in `ci.json`.
  `claude-review.yml` is retired (the pipeline's review job replaces it);
  `ci.yml` and the other workflows are untouched. Red on day one: coverage
  82 % under the 90 % floor, and the Windows install leg.

### Security

- Pillow now requires version 13.0.0 or newer to address the advisories affecting
  12.3.0, including GHSA-5x8w-8jj5-q52h. Pillow 13 requires Python 3.11+, so
  Python 3.10 users must upgrade. The plugin bootstrap selects its managed
  Python on older interpreters; direct package installations require 3.11+.

- The Claude Code workflows are aligned with the documented Claude Code GitHub Actions setup (https://code.claude.com/docs/en/github-actions, "Run a skill" and "Respond to @claude mentions"): the PR review runs the code-review plugin skill with `--comment` under read-only review permissions, and no checkout names the PR head ref, which clears CodeQL `actions/untrusted-checkout`.
- The Claude Code PR review no longer checks out PR code in a privileged workflow (CodeQL `actions/untrusted-checkout/high`, `actions/untrusted-checkout-toctou/high`): the review job moves to `.github/workflows/claude-review.yml`, triggered by `pull_request` only, and `.github/workflows/claude.yml` keeps only the `@claude` job on its comment, review and issue triggers, with no PR head checkout.
- **Personal data is stored owner-only (ADR-1112).** The 2026-10-21 audit
  (E18) measured `memory.db`, logs and telemetry at 0644/0664 in 0755/0775
  directories. Under `~/.claude/methodology`, the capture worker directory,
  `brain-index.json` and the cache root (`~/.cache/cortex`, which now follows a
  relocated `CORTEX_CLAUDE_DIR` like the rest of Cortex's data), files are now created 0600 and
  directories 0700 (the SQLite database before SQLite opens it, so its WAL and
  shared-memory files follow); existing installs are tightened once at server
  or session start (directories 0700, files lose group/other bits, symlinks
  untouched), and on Windows the roots get a user-only inherited ACL. Files
  written into a user's repository keep the umask.
- **A hard `forget` erases every stored copy of the memory (ADR-1111).** The
  2026-10-21 audit (E15) found the full original text left in
  `memory_archives` after a hard forget. `store.erase_memory` now deletes, in
  one transaction on both backends, the row with its FTS and vector entries,
  its archives, the wiki claims, drafts, citations and compiled page derived
  from it, the reminders and rules mined from it, its receipts and stage
  history, and the text entities only it referenced; page files compiled or
  promoted from it are removed and the wiki index rebuilt. A failing step
  rolls everything back and raises (the old handler logged a failed claim
  deletion and deleted the row anyway). SQLite runs with `secure_delete`, FTS5
  `secure-delete` and a WAL truncation, so the bytes leave the file too. The
  result reports what was erased.
- **One redaction gate on every write into storage (ADR-1110).** The 2026-10-21
  audit (E16) found the secret scrubber on the capture hook only, missing
  GitHub, Anthropic and OpenAI keys and JWTs, while `remember`, session import
  and session end stored text unfiltered. Now:
  - the detector is the gitleaks 8.30.1 default rule set, vendored byte-identical
    under `third_party/gitleaks/v8.30.1/` (sha256-pinned, MIT, in the release
    SBOM), translated to Python by `scripts/vendor_gitleaks_rules.py` (217 of
    222 rules; the five that need a file name cannot apply to text) and applied by a port of
    gitleaks' decision procedure, with exact parity against the binary on the
    repository tree and on a real-format fake-credential corpus
    (`scripts/redaction_parity.py`, run in CI); a second pass catches keys
    followed by sentence punctuation, which six gitleaks rules miss;
  - SQLite and PostgreSQL store connections are built gated: every write
    statement, through any helper, pool, cursor, `executemany` or COPY, binds
    redacted parameters; embeddings, the SQLite FTS augmentation and artifact
    addresses are derived from redacted text;
  - files are written only through `shared/gated_files.py`, child processes log
    through a redacting relay, file log handlers carry a redacting filter; an
    architecture test fails on any other storage primitive in `mcp_server/`;
  - `.pre-commit-config.yaml` (gitleaks hook) and a blocking `secret-scan` CI job
    (full history and tree, pinned and checksum-verified binary).

### Added

- `.github/workflows/claude.yml`: every push to a PR runs a Claude Code review (`/code-review` then `/security-review`, one cycle), applies the findings and arms squash auto-merge; `@claude` in a comment or issue runs Claude on that request. Action pinned by SHA (anthropics/claude-code-action v1.0.256).
- **Per-project export and import of memories (ADR-1113, GDPR art. 20).**
  `python -m mcp_server.portability export <project-root> <file>` writes the
  current memories of a project and its subdirectories (never a sibling or the
  parent; global memories with `--include-global`) as JSON Lines with a
  versioned header, every value redacted, file mode 0600;
  `import <file> [--into <root>]` validates the file, relocates directories,
  recomputes embeddings and skips memories already present.

- **The Claude Code plugin runs its own PostgreSQL server (#744, #740;
  ADR-1114).** On macOS (arm64, x86_64) and Linux glibc (x86_64, aarch64),
  Setup (`claude --init-only`) on a fresh install downloads the pinned
  theseus-rs PostgreSQL 18.6.0 and a pgvector 0.8.7 archive (sha256-checked,
  about 13 MB), runs `initdb --pwfile`, starts the server on 127.0.0.1 with
  its cluster in `~/.claude/methodology/managed-pg` (uninstalling the plugin
  never deletes memories), creates `vector`, `pg_trgm` and the schema, and
  only then selects it. No Homebrew or system PostgreSQL is needed: the macOS
  binaries carry their own OpenSSL (pg0, used by the earlier draft of this
  change, loaded Homebrew's and failed in dyld on a Mac without it). The
  pgvector archives are compiled by Cortex's CI (`pgvector.yml`: pinned
  upstream commit, built and load-tested against the pinned PostgreSQL on each
  platform, build provenance attested) and published from main only as a
  release of this repository. The server is started and stopped on kernel events (ready in
  `postmaster.pid`, process exit), never on a timer, and a postmaster is
  adopted or signalled only when its PID and kernel start time are the ones
  recorded at spawn and it authenticates with the cluster's password (a
  wrong server signature, a foreign nonce, trust or a cleartext request is
  refused). A postmaster that dies under live clients is started again on the
  same port, and a client never takes a `running` status whose postmaster is
  dead; one whose supervisor died before recording it is adopted once it
  proves itself; a live postmaster of the cluster that Cortex did not start
  is named and left alone, its `postmaster.pid` never removed. The Codex hook entry and `hypermnesia-mcp` stop in one line
  (`Cortex not ready: ...`) when the server cannot run. The
  Codex plugin, `hypermnesia-mcp` and `cortex-doctor` attach to the same
  server, so Claude and Codex on one account share one store. A configured
  `database_url` (`CLAUDE_PLUGIN_OPTION_DATABASE_URL` for hooks and Setup)
  always wins, in Setup too; a server that cannot start leaves the SQLite
  store selected, recorded as `sqlite_fallback` in the Setup outcome and shown
  at session start as `SQLite fallback: <cause>`; Windows, musl and Linux
  hosts missing `libxml2.so.2` or OpenSSL 3 keep SQLite. Existing SQLite
  stores are not migrated. `setup_db.py` now fails when a schema statement
  fails instead of reporting ready with warnings.
- **Benchmark refresh preparation: pinned datasets, a per-query journal,
  offline token counting and energy per scored query.** Scores and retrieval
  are unchanged; nothing here runs a scored benchmark.
  - `--only longmemeval-cleaned` runs LongMemEval-S on the 2025-09 cleaned
    release, pinned by revision `98d7416c` and sha256, with a preflight on
    bytes, record count (500) and the keys the runner reads. The artifact is
    `longmemeval-s-cleaned.json`, never judged against the floors measured on
    the original file; an empty `--only` keeps the historical set.
  - BEAM loads `Mohammadta/BEAM` at a pinned revision (data identical to the
    only data upload). Every result manifest carries `dataset`, gathered into
    the run `MANIFEST.json` under `datasets`.
  - With `--results-out`, the LongMemEval, LoCoMo and BEAM runners write
    `<stem>.queries.jsonl` (retrieved ids, sources, sizes, sha256, optional
    text with `--query-log-content`) and `<stem>.phases.jsonl` (ingest and
    recall wall-clock windows), after retrieval returns.
  - `benchmarks/tokens/count_tokens.py` counts, offline and separately from
    scoring, retrieved-text and bench-equivalent recall-payload tokens (json
    and tabular) with Anthropic's `count_tokens` for one pinned model, plus
    the full LongMemEval history for the retrieved-vs-full ratio.
  - `benchmarks/energy/run.sh` with `ENERGY_ENTRY=run_external_energy.py`
    measures a benchmark from its own phase timeline: whole-leg energy per
    scored query (an upper bound) and per-condition energy, with SCI carbon.
    Energy results measured on real benchmark runs may now be committed,
    quoted with their machine, region and boundary.

### Fixed

- The `@claude` mention workflow (`.github/workflows/claude.yml`) checks out full history and can run git, gh and the test runners.
- **No hook installs dependencies any more; run `claude --init-only` after
  `claude plugin install` and after `claude plugin update`** (ADR-1108,
  replacing ADR-1104 decision 4). Every hook used to install whenever its
  dependency stamp did not match, inside a 5 to 30 s budget (300 s for
  SessionStart): the host cancelled hooks mid-install, and one plugin data
  directory held 64 orphaned `deps.tmp-<pid>` scratch directories. The
  plugin's Setup hook (`claude --init-only`, or `scripts/init_plugin.py`,
  which shows progress and exits 1 with the cause) now installs the base
  set, the semantic-search set and the model in the foreground. Without that
  step, SessionStart says Cortex is installing, the edit gates let edits
  through and say they are inactive, other hooks exit 1 (non-blocking), and
  one detached job installs. Sets live in `sets/<key>/`, keyed on the locked
  dependency set rather than the plugin version, so a release that keeps its
  dependencies needs no install. Nothing asks a git remote for releases: the
  next version's set is pre-installed only when the local marketplace clone
  already holds it (after `claude plugin marketplace update`). Sets no
  installed version uses are removed, and a path that cannot be removed is
  reported, never declared removed. Dead installs' scratch is reclaimed.

- **A recall pool no longer chooses which tied rows a signal credits**
  (ADR-1109). Each `recall_memories()` pool (vector, FTS, trigram, heat,
  recency) kept its best `max_results * 10` rows; when more rows shared the
  score at the cut, ADR-1106's newest-first tie-break decided which of them
  got the signal (LoCoMo conv-41: 122 rows at heat 0.05, the oldest 22
  lost the heat contribution). Every pool now keeps its whole boundary tie
  group (`FETCH FIRST ... ROWS WITH TIES`). On SQLite, whose fusion is
  rank-based, the signals keep the same membership (sqlite-vec's KNN cut
  included) and tied rows share the mean `w / (k + rank)` of the positions
  their group occupies instead of ranks assigned by age. Existing databases
  get the new function on the next store open (schema hash). Measured:
  LoCoMo R@10 0.8860, MRR 0.7768 (ADR-1106: 0.8870 / 0.7780), identical
  across two runs; LongMemEval-S 0.9820 / 0.9059. On SQLite a tie group past
  the pool is kept as a predicate with one shared credit and filled newest
  first, never read row by row: it is counted once over a covering index
  built on the first open (a grouped count that also lists the group's
  capture origin and agent pairs), and its rows are read with one ordered
  seek per pair. On the production arguments (trust factor 0.7) and the
  owner's agent vocabulary (421 pairs), a store whose memories share one
  heat recalls in 21.9 to 25.1 ms at 250,000 memories and 5.5 to 8.3 ms at
  40,000 (before: 2 to 4 ms): the grouped count, 0.9 to 2.7 times a plain
  count and kept by owner decision, plus a fill that grows with the number
  of pairs; where memories also share one `created_at`, 24.4 to 44.3 ms at
  250,000. With a realistic heat spread recall is within 3 ms of the
  previous level.
  sqlite-vec's KNN serves k up to its cap of 4096 and a larger pool reads
  the same distance through `vec_distance_l2`, so any
  `max_results` works; id sets bind as one JSON array; a vector-signal
  failure now raises instead of silently dropping the vector signal.
- **Recall returns the same memories whatever the table's physical layout**
  (ADR-1106). Every `ORDER BY ... LIMIT` on the recall path cut exact score
  ties in heap order, which VACUUM, CLUSTER and free-space reuse change: the
  five `recall_memories()` pools, its final cut, `spread_activation_memories()`,
  `search_fts`, `search_by_tag_vector`, the hook queries (auto-recall, the
  agent briefing on both backends, the SessionStart banner) and the listings
  they and `include_related` read (`get_hot_memories`,
  `get_memories_mentioning_entity`, `get_entities_for_memory`,
  `get_relationships_for_entity`). LongMemEval
  `f4f1d8a4` (110 rows at heat 0.05) dropped 10 arbitrary rows from the heat
  pool, and two runs of the same commit gave different scores. Exact ties now
  go to the newer memory (`created_at DESC, id DESC`) on PostgreSQL and SQLite;
  an ORDER BY on stored `heat_base` uses `id DESC` instead, which its
  `(heat_base, id)` index serves (with `created_at` in between,
  `get_hot_memories(limit=10)`, read on every `remember`, took 159.5 ms
  instead of 0.16 ms on a 68k-memory store); entity name lookups take the
  oldest row, the one `insert_entity` returns.
  Existing databases get the new function on the next store open (schema
  hash). The HNSW plan is kept (Index Scan + Incremental Sort).
- **Recall and every vector query reach past `hnsw.ef_search`** (ADR-1105).
  pgvector's HNSW index returned at most 40 candidates before the filters
  (superseded, stale, other domain, heat, tag, age) were applied, so relevant
  memories behind filtered neighbours were silently dropped and the
  `recall_memories()` vector pool (`max_results * 10`) never got past 40.
  Every store connection (pools, persistent connection, reconnects) now runs
  `SET hnsw.iterative_scan = relaxed_order`; the three Python ANN queries
  re-sort outside a materialized CTE. Read-only on the owner's store (68,496
  memories, 100 queries): recall's top-10 equals the exact (index-free)
  ranking for 81 queries instead of 51; vector-pool recall against an exact
  scan 0.578 -> 0.939. **Requires pgvector >= 0.8.0**: the store refuses to
  start on an older loaded library (it would drop the setting with a warning
  only), and `python -m mcp_server.doctor` (also its `mcp` subcommand and
  the `check_setup` tool), `scripts/setup_db.py` and `scripts/setup.sh` check
  it. The near-duplicate scan shares the same check, and the benchmarks'
  deterministic session sets it again after its `DISCARD ALL`.
- **The near-duplicate apply pass no longer supersedes memories through a
  chain** (ADR-0370). It grouped pairs at or above the threshold into
  connected components, which is single-linkage: A~B and B~C put A and C
  together whatever sim(A, C) was, and every member was superseded into the
  component's one survivor. On a restored copy of a 66,707-memory store at
  0.90 (dry run), the largest component had 15,812 members, and 20,264 of
  the 26,534 rows to supersede were below 0.90 to their survivor (lowest:
  0.33). Each component is now split into survivor-anchored groups. The
  survivor is elected by the unchanged rule (heat, then `created_at`, then
  id). A member joins it only if their own similarity, computed in SQL from
  the two embeddings (`ids_near_to`), is at or above the threshold. The
  remaining members form their own groups in later rounds. On the same
  copy: 4,492 groups, 24,110 rows, largest group 6,000, minimum similarity
  to the survivor 0.900005, 1,164 members left unmerged, 100 to 150 s
  against 69 s. Two passes over the same member stats give identical journals;
  two passes a few minutes apart differed in 5 of 4,492 groups, because
  decay moved effective heats that tie at `REAL` precision. The journal keys are unchanged.
  `component_size` is now the group's size, and the result gains
  `unmerged_total`.

- **The near-duplicate scan covers every live memory, the same way on every
  run** (ADR-0557). Its anchors were `LIMIT 20000` with no `ORDER BY`, so on
  a larger store each pass scanned an arbitrary subset: on a restored copy
  of a 66,547-memory store two runs gave 199,400 and 236,626 pairs. The scan
  now reads every anchor in id order, 5000 per query (keyset pagination,
  one transaction per batch with the iterative-scan check), and merges the
  pairs. On the same copy: 686,268 pairs, identical over two runs and for
  batch sizes 1000, 5000 and 20000, 47 to 88 s, 214 MB peak Python
  allocation. `anchor_limit` is removed from `list_candidate_pairs`,
  `run_near_dup_sample` and `run_near_dup_apply_pass`; the scan takes
  `batch_size`, which bounds one query, not coverage.
- **The near-duplicate scan pairs duplicates that superseded rows used to
  hide** (ADR-0557). Its per-anchor top-K used the HNSW index, which returned
  at most `hnsw.ef_search` (40) candidates before `current_memories`
  filtered superseded rows and the scan filtered stale ones; 300 superseded
  rows around a pair hid it. The scan now runs with
  `SET LOCAL hnsw.iterative_scan = strict_order`, which needs pgvector 0.8.0
  or later: the scan asks the loaded library whether the parameter exists
  and raises when it does not (a library without it would drop the SET with
  a warning and run the lossy scan). On a 66,490-memory
  store: 17 more pairs, none lost, 10 s against 11 s. The intermittent
  local failures of `test_near_dup_calibration_pass.py` had a test-side
  cause: rows deleted by earlier tests stay in the index, and identical unit
  vectors left new rows unreachable; those tests now start from an emptied
  `memories` table (`tests_py/_pg_hnsw.py`).

- **A marketplace install reaches "Cortex ready" at the first session with
  no other step** (ADR-1104). Measured on main with the real Claude Code CLI
  on a clean HOME (`scripts/install_e2e/run.py`): the plugin's `postInstall`
  is not a manifest field the host runs, so no backend marker existed and
  every process got `DATABASE_URL=postgresql://localhost:5432/cortex`; the
  Mac's `/usr/bin/python3` (3.9.6) could not install the locked sets; a cold
  install (58 s) outlived both 30 s host timeouts, so the hook output was
  discarded and the MCP server was marked failed for the session; the
  SessionStart hook installed the 1 GB ML set inline and the server started
  an unpinned `pip install sentence-transformers`; the deps lock let a waiter
  proceed unlocked after 30 s. Now: no configured database means the SQLite
  store (a configured `database_url`, `CORTEX_MEMORY_STORE_BACKEND` or an
  installer marker still wins, and hooks read the same option as the
  server); below Python 3.10 the launcher installs CPython 3.12.13 with the
  pinned uv and re-runs on it; an uninstalled MCP server is fronted by a
  stdlib stand-in that answers the host at once and hands over with
  `list_changed`; the SessionStart hook (timeout 300 s) installs the base
  set and shows "Cortex ready: <store>, <n> memories; <how recall ranks>"
  or "Cortex not ready: <cause>"; semantic search installs in one background
  job from `uv.lock`; installs hold an OS lock released on the holder's
  death. A backend marker that exists but is invalid is an error naming the
  file, never read as absent; a stand-in whose server cannot start answers
  every request with that cause. The `postInstall` field and the PostgreSQL install recipes printed
  by the hook are removed. `scripts/install_e2e/run.py` runs in CI on Linux
  and macOS.

- **SessionStart starts at most one background code-graph ingest per project
  per TTL window, and an unreadable memo starts none** (#751). The issue
  reported a psycopg-only memo lookup that returned None on SQLite; #749
  (ADR-1104) had already routed the SQLite read through the store on main.
  What this changes relative to main: the PostgreSQL read also goes through
  the configured store (`ingest_helpers.materialised_graph_paths`, shared
  with `find_cached_graph`), where it opened its own psycopg connection; a
  store failure on either backend now spawns nothing, where a PostgreSQL
  failure returned None, so the graph looked stale and an ingest started;
  only a memo whose graph file still exists counts as cached; and
  `pipeline_graph_ttl.claim_reanalysis_slot` claims each project's TTL window
  with one atomic create (`O_CREAT | O_EXCL`) of a window-keyed stamp, so a
  failed, slow or concurrent ingest, or two sessions starting together, no
  longer start a second one within `CORTEX_PIPELINE_GRAPH_TTL_HOURS`
  (default 24 h). The winner removes the project's stamps of strictly
  earlier windows only, so a claimer delayed across a window boundary never
  removes the next window's stamp.

- **The PostToolUse impact bump raises heat on SQLite too, and targets the
  session's project** (#750). `pipeline_impact_bump` paid for the graph
  lookup and the `detect_changes` call on every edit, then raised heat with a
  psycopg-only `UPDATE` that did nothing on SQLite. The same single `UPDATE`
  now runs through the configured store's connection on both backends
  (`file_memory_priming.bump_memories_mentioning`, sharing the I2-allowed
  writer of the file-cue boost): every memory whose content contains any
  impacted symbol, case-insensitively, with no row limit (`_MAX_BUMPS` still
  caps the symbols, as on main), except stale, benchmark and saturated
  (heat 1.0) ones; heat is capped at 1.0 and `heat_base_set_at` and
  `last_accessed` are refreshed. It also resolved the project as
  `CLAUDE_PROJECT_ROOT or os.getcwd()`, the plugin root under the launcher;
  it now uses `resolve_project_root(event, os.environ)` and does nothing when
  the project is unresolved.

  Behaviour change: reanalysis windows are fixed and aligned to TTL
  multiples (they were sliding), so two ingests can start just either side
  of a boundary. The impact bump differs from main's `UPDATE` in three
  ways: superseded memories are no longer bumped (`get_hot_embeddings` ranks
  every row by `heat_base` under a LIMIT, so a bumped superseded row took a
  current row's slot; ADR-1086 already excludes them from the file-cue
  boost);
  `_` and `%` in a symbol match literally, where `ILIKE` read them as
  wildcards; and on SQLite case folding covers ASCII letters only.

- **The background code-graph re-analysis ingests the session's project,
  never the plugin root.** `scripts/launcher.py` `chdir`s to the plugin root
  before it runs a hook, yet `session_start._maybe_background_reanalyze` and
  `post_commit_reindex` took `CLAUDE_PROJECT_ROOT or os.getcwd()` as the
  project, and `pipeline_discovery` scanned its sibling source checkouts
  (`../ai-architect-mcp-codebase`, ADR-0584) relative to the cwd. Without
  `CLAUDE_PROJECT_ROOT` the hooks therefore spawned a detached ingest of the
  plugin directory, found through the plugin's siblings. In the test suite,
  run from a checkout with that sibling, `tests_py/hooks/test_entry.py` left
  the worker and its `ai-architect-mcp-codebase` child alive, which the #679
  leak guard reported at teardown. Both hooks now take the project from
  `resolve_project_root(event, os.environ)` (issue #604) and spawn nothing
  when it is unresolved; `discover_pipeline_command` and
  `ensure_pipeline_connection` take the project root as their sibling-scan
  anchor, and `None` scans no sibling. The server probe anchors on
  `CLAUDE_PROJECT_ROOT`, which only the hook dispatcher exports, so in the
  MCP server process the sibling scan is off unless the host exports it: a
  server started from a checkout next to `../ai-architect-mcp-codebase` no
  longer finds that build (marketplace and `PATH` discovery are unchanged).
  `setup.sh` anchors on the checkout it installs, never on its cwd.

- **Hooks write UTF-8 to stdout and stderr on every platform and entry point,
  and the wiki reindex reads and writes UTF-8** (#688). A text-mode stdout
  encodes with the locale code page (cp1252 on a Windows pipe), so
  `auto_recall` died with `UnicodeEncodeError` on the `U+27E6` that opens every
  injection receipt. Only the plugin launcher reconfigured its streams (with
  `errors="replace"`); the Codex `hypermnesia-mcp-hook` entry and a direct
  `python -m mcp_server.hooks.<hook>` run did not. The decision now lives in
  one place, `mcp_server/hooks/output_streams.py`: stdout is strict UTF-8 (a
  lone surrogate fails loudly, nothing is replaced), stderr is UTF-8 with
  CPython's own `backslashreplace`, and a stream that cannot be reconfigured
  raises. Every hook `__main__` block that writes, `hooks/entry.py` and the
  launcher call it; `tests_py/hooks/test_output_streams_guard.py` fails a hook
  entry point that writes without it. `scripts/setup.py` (piped through `tee`
  by the installer) uses it too, three developer-script arrows outside cp1252
  are now ASCII, and `wiki_reindex_io` and the Codex `session_queue` error file
  no longer use the default encoding. The doctor entry points (`cortex-doctor`
  and `cortex-doctor mcp`) set stdout to UTF-8 first: their fix hints print
  `U+2192`, and on a cp1252 pipe they died on the failure they were reporting.
  Product code that decodes a child process's output names the encoding (`uv`,
  `git`, the Codex session queue). The decision is ADR-1098.

- **`benchmarks/lib/bench_regression.sh` runs under the macOS system bash
  3.2.57** (#690). The baseline worktree cleanup trap expanded a function-local
  `wt_dir` when it fired; under `bash -c` and 3.2 the locals are already gone
  then, so `set -u` aborted with `wt_dir: unbound variable`, the worktree was
  left behind and the runner's exit status was lost. The trap body is now built
  when it is set. `test_bench_regression_datasets.py` runs under `/bin/bash` and
  the first `bash` on `PATH`.
- **`scripts/mutation_check.sh` refuses an empty test list** (#690 sibling
  search). The first argument empty used to exit 0 under `/bin/bash` 3.2.57
  (mutmut ran on one empty test name) and exit 1 under bash 5.3 (no tests to
  collect); both now print an error and exit 2.

- **Windows: each Claude window gets its own session identity, and no liveness
  probe can signal a live process** (#665). Three causes, one fix each. (1) The
  registry walked ancestors with `ps -o`, which Git Bash does not have; the
  walk now reads the Windows process table through a small `ctypes` layer
  (`mcp_server/shared/win32_process.py`, kernel32 only, no new dependency).
  (2) The match was `basename == "claude"` while the process is `claude.exe`;
  it is now a case-insensitive `claude.exe` match on the nearest ancestor, with
  a creation-time check so a recycled parent pid is never followed. (3) The MCP
  server's parent is `cmd.exe`, not `claude`; on Windows the reader walks to
  the `claude.exe` ancestor instead of calling `os.getppid()` and caches it for
  the server's lifetime. POSIX paths are unchanged. Separately, every
  `os.kill(pid, 0)` liveness probe (`session_registry`, `GroomerCoordinator`,
  the launcher's backup sweep) is replaced by one `pid_alive`
  (`mcp_server/shared/process_liveness.py`). On Windows `os.kill` is no
  existence check and was a live hazard: signal 0 goes to
  `GenerateConsoleCtrlEvent(0, pid)`, and in CPython 3.10, 3.11, 3.12.0 to
  3.12.8 and 3.13.0 to 3.13.1 a failed call falls through to
  `TerminateProcess(handle, 0)` (gh-58689, fixed in 3.12.9 and 3.13.2 by
  gh-128932), then raises `SystemError`; a pid that is not a console group id
  acts as group 0 and sends Ctrl+C to the whole console (gh-87128). The
  Windows probe is now `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
  `GetExitCodeProcess`; the decision is ADR-1096.
- **Windows: hooks decoded their event JSON as cp1252, so captured memories
  stored mojibake (#664).** Claude Code and Codex write the hook event as
  UTF-8, but a text-mode `sys.stdin` decodes with the locale code page, so
  `é` was stored as `Ã©` and bytes with no cp1252 mapping became lone
  surrogates that failed on write. Every hook now reads its event through
  one reader, `mcp_server/hooks/stdin_event.py`, which decodes the bytes of
  `sys.stdin.buffer` as strict UTF-8; invalid bytes raise
  `HookStdinDecodeError` instead of being replaced. The failure is loud and
  never blocks: every hook, the PreToolUse gates included (ADR-1060), exits 1
  with a `[hypermnesia-mcp-hook]` (Codex) or `[cortex-launcher]` (Claude)
  line. The Codex
  `session_queue.py` intake decodes the same way. Unverified on a real
  Windows host: the cause is simulated with a cp1252 `TextIOWrapper`.
  Memories already stored garbled are not repaired by this change.

### Changed

- `.github/workflows/claude.yml`: the @claude mention workflow can run ruff, uv, pipx, coverage, tsc, shellcheck and the Claude CLI.
- **`uv.lock` is the only dependency source (ADR-1092).** The thirteen
  generated `requirements/*.txt` exports, their generator and the launcher's
  hand-kept pins are gone. CI jobs, the three Docker images and the
  ClusterFuzzLite build install with `uv sync --locked`, hash-verified; the
  plugin launcher and `scripts/setup.sh`/`setup.py` export one locked set as
  a `pylock.toml` and install it with `uv pip install --require-hashes`.
  When no uv 0.11.3 is on `PATH`, the launcher installs that exact uv wheel
  with pip, hash-checked, beside its `deps/` directory, with no prompt; if
  that fails, it says why and how to install uv by hand. Dependabot now uses
  its `uv` ecosystem, which rewrites `pyproject.toml` and `uv.lock`
  together, so its Python PRs no longer need a resync commit: the grouped
  update the real updater produces for this lock (45 packages) passes
  `uv lock --check`, ruff, pyright and the full suite as produced. Six
  packages locked per platform (torch, onnxruntime, numpy, transformers,
  sentence-transformers, cryptography) are excluded from Dependabot, which
  can only request one version of a package, and are bumped with
  `uv lock --upgrade-package` (CONTRIBUTING.md). The launcher
  reinstalls a set only when `uv.lock` changes that set: a lock change
  elsewhere (a development tool) is recognised with one offline `uv export`
  and downloads nothing. Every macOS the old pip resolution served keeps a
  working ML stack from the lock, macOS 12 included (onnxruntime 1.19.2).

## [4.23.5] - 2026-09-23

### Fixed

- **The SQLite backend now installs sqlite-vec on every platform, and a
  memory is never mislabelled as having a vector it doesn't have (#634).**
  Neither the plugin launcher's runtime dependency pins nor `scripts/setup.py`'s
  install closure (`requirements/setup.txt`) ever named the `[sqlite]` extra —
  only `postgresql`, `codebase` and `benchmarks` were installed, unconditionally,
  regardless of which backend was chosen. The zero-config SQLite default
  therefore ran with vector search silently disabled (FTS-only) on every
  install, reported by `check_setup`/`doctor` as fully ready. Separately,
  `SqliteMemoryStore` stamped `embedding_model='neural'` on a memory whether
  or not its vector actually persisted, so a memory written while sqlite-vec
  was unavailable could be mislabelled as vector-backed and never resurface
  for repair. Fixed: `sqlite-vec` is now part of the base install set and of
  `requirements/setup.txt`'s generated closure; existing installs self-heal
  on next launch; the store now stamps `'neural'` only after the vector
  itself is confirmed written (`'fallback'` keeps stamping unconditionally,
  per its own pre-existing contract), and the re-embed worklist self-heals
  any row a prior install already mislabelled; `doctor`/`check_setup`'s
  vector-search check is required, not optional, since sqlite-vec now ships
  by default.
- **A failed `scripts/setup.py` no longer discards the plugin's backend
  decision (#633).** `install-plugin.sh` wrote `~/.claude/methodology/backend.json`
  only after running `scripts/setup.py`, guarded by `|| fail ...`. Any setup
  failure (a Windows torch/torchaudio conflict, a network blip during
  dependency install) discarded a correctly-chosen SQLite backend; on the
  next launch, the missing marker left the engine on its "auto" default,
  which requires PostgreSQL under the plugin's `CORTEX_RUNTIME=""` (resolves
  to "cli") setting — silently turning a zero-config SQLite install into a
  hard PostgreSQL requirement with none ever provisioned to satisfy it.
  Fixed: the marker now persists immediately after the backend is decided,
  before setup can fail and exit. Separately, `scripts/setup.py`'s
  `cache_embedding_model()` and its macOS/Linux twin
  `scripts/lib/precache_embedding_model.sh` now isolate their child process
  from user site-packages the same way `scripts/launcher.py` already does
  (issue #621), closing the one remaining gap that could still abort the
  embedding-model pre-cache on a conflicting environment; and
  `scripts/setup.py`'s dependency-check step now reports a `[FAIL]` row
  instead of crashing outright when that class of import failure occurs.
- **`consolidate`'s wiki maintenance cycle silently broke four passes on
  every SQLite run while reporting `status: "ok"` (#636).**
  `wiki_source_backfill_pass`, `wiki_domain_backfill_pass`,
  `wiki_citation_seed_pass`, and `wiki_backlog_pass`'s lesson-promotion
  count all accessed `store.batch_pool` (a PostgreSQL-only connection
  pool) unconditionally; each raised `AttributeError` on the SQLite
  default backend, three of the four caught it internally and returned
  an `"error: ..."` stanza, and `wiki_maintenance.py`'s own escalation
  only fired on a *raised* exception, never on a returned error status —
  so `consolidate` kept reporting overall success while four maintenance
  passes were broken on every run, on the default backend. Fixed: the
  backend is decided once, at the top of `run_wiki_maintenance`, and the
  four PostgreSQL-only passes are invoked only when the store actually
  provides `batch_pool`; on SQLite their keys are simply absent from the
  response, the same way `consolidate`'s other optional sections behave
  when disabled, and a genuine failure inside any of the four now raises
  and is caught by the function's own (previously dead) error boundary
  instead of being swallowed at the call site.
- **Windows CI now actually exercises the SQLite-vec install path and
  the wiki maintenance fix above** — the platform every reporter of
  #633/#634/#636 was running. A new verifier
  (`scripts/verify_sqlite_extra_parity.py`) checks every package
  `pyproject.toml`'s `[sqlite]` extra declares actually resolves under
  the real install path's own `deps/` directory, the same check that
  would have caught #634 directly.

## [4.23.4] - 2026-09-23

### Documentation

- Describe native Codex memory capabilities directly alongside Claude Code,
  including automatic context, capture, checkpoints and shared project memory.
  Remove stale pre-fix limitations and explain hook trust during installation
  and updates.
- Publish native macOS verification traces for Claude-to-Codex and Codex-to-Claude
  memory retrieval, project-scoped exclusion, and automatic startup context in
  both hosts. The report names the exact tested versions and includes sanitized
  tool responses and transcript hashes (#632).

## [4.23.3] - 2026-09-22

### Fixed

- Codex lifecycle hooks use the MCP storage factory when no backend is configured,
  so automatic context reads the same SQLite store after PostgreSQL fallback.
  Explicit database targets and saved backend selections retain precedence.
  The MCP store also treats `CORTEX_MEMORY_DATABASE_URL` as an explicit target
  and refuses an unrequested SQLite fallback when that target is unavailable.
- Preserve the explicitly attached project directory when priming memories from
  file reads through a symlink alias. Previously, a memory stored under a macOS
  `/var/folders` path was missed because priming queried `/private/var/folders`.
  Project scope and cooldown keys now preserve the same directory identity, so
  a read through one alias cannot suppress another scope. Both storage backends
  retain foreign-project isolation (#629).

## [4.23.2] - 2026-09-22

### Fixed

- Codex subagents receive scoped team decisions and role context at native
  start on PostgreSQL and SQLite. Plaintext spawn calls also receive task-specific
  memory; opaque collaboration arguments remain unchanged.
- Shell file-access cues prime current project/global memories. Priming respects
  the configured backend and excludes sibling projects, stale and superseded
  records, and benchmark data.
- Session-end intake persists events before package startup. A detached worker
  records session/profile effects with idempotent replay after interruption;
  startup recovers pending work and reports failures.
- Codex runtime commands pin the matching wheel version so package caches cannot
  retain the previous hook behavior after a plugin update.

- **The vendored `deps/` directory is now isolated from user site-packages
  (#621).** `scripts/launcher.py` put `deps/` first on `sys.path` and left
  the interpreter's user site-packages behind it, which is not isolation in
  either direction. Every package `deps/` does not vendor kept resolving
  from user site-packages: on a Windows machine carrying a coherent CUDA
  torch/torchvision/torchaudio set, `torch` came from `deps/` (CPU) while
  `torchvision` came from user site-packages built against the other torch,
  so importing them together aborted the MCP server during startup with
  `RuntimeError: operator torchvision::nms does not exist`, which
  `transformers` re-raised as a misleading `ModuleNotFoundError: Could not
  import module 'PreTrainedModel'`, and which the host reported only as
  `CONNECTION_CLOSED`. Conversely, `sys.path.insert` never processes a
  directory's `.pth` files, so `deps/pywin32.pth`, the only route to
  `pywintypes`, was inert, and cutting user site-packages on its own
  (`PYTHONNOUSERSITE`, `python -s`) traded one import failure for another.
  A new stdlib-only `scripts/launcher_site.py` does both halves in the
  order that works: `site.addsitedir(deps_dir)` so the `.pth` files run,
  then drops every `sys.path` entry that resolves to the user
  site-packages directory or sits under it (`site` has already appended a
  user-installed pywin32's `win32` and `win32/lib` from that directory's
  own `.pth` files by the time any of this runs). It owns the `sys.path`
  insert as well, so no call site can perform the two steps out of order. `scripts/launcher.py`
  applies it to the MCP server and all eleven lifecycle hooks at once —
  twice, once before `ensure_deps`/`ensure_all_deps` and once after, since
  that install resolves transitives and can land a `.pth` the first call
  could not see, and `scripts/setup.py`'s verification block applies it
  too, so the installer checks what the plugin will actually import.
  Inside a virtualenv (dev clones, CI) user site-packages is already off
  `sys.path`, so the removal is a no-op there. A `site.getusersitepackages()`
  that cannot resolve now reports the cause on stderr instead of silently
  leaving `deps/` unisolated.

- **The installer names the check that actually failed (#621).** When
  `scripts/setup.py` failed, `install-plugin.sh` ended with "PostgreSQL
  must be installed and running first" whatever the run had reported —
  including the run above, whose four PostgreSQL checks all passed and
  whose only failing row was `sentence-transformers`. A new
  `scripts/lib/setup_py_step.sh` captures the run's output and echoes back
  its `[FAIL] <check>` rows; the PostgreSQL install guidance survives as a
  conditional instead of an assertion. Capturing the output means piping
  it, which would block-buffer the child's stdout and hide the whole
  install until it ended, so the run is made unbuffered: measured, a
  `print()` followed by a two-second sleep reaches the reader at t+2s
  through a pipe and at t+0s with `PYTHONUNBUFFERED=1`. Carriage returns
  are stripped for the same reason the message exists: CPython's
  text-mode stdout writes CRLF on Windows and a pipe preserves it, so the
  extracted name arrived as `sentence-transformers\r` and the rest of the
  installer's line overwrote it from column 0.
- A `wiki_write` pointer memory is no longer re-materialised as a wiki page
  (#622). `wiki_write`/`wiki_adr` register one memory per authored page so
  the page surfaces in `recall`; that memory carries a prefix of the page's
  own markdown. `remember` handed it to `wiki_sync.build_from_memory` like
  any other memory, and a tag such as `architecture` admitted it, so the
  classifier wrote a second page from the pointer: the authored
  frontmatter copied into the body, a `title:` YAML line as the H1, a kind
  inferred rather than read (`rfc/_general/` for a page declaring
  `kind: explanation`), and the body cut mid-word. A new
  `shared/wiki_pointer.py` owns the identity of a pointer memory, keyed on
  the `wiki://` origin prefix; `build_from_memory` and `sync_memory_strict`
  now take that origin inside a `PageCandidate`, and `wiki_extract`'s
  candidate query excludes pointers on every branch. `is_pointer_source`
  is the single authority: the SQL clause only narrows the candidate set,
  so a `source` value padded with whitespace, which LIKE cannot see, is
  still turned away rather than slipping past the second door. The
  pointer memory itself is unchanged: removing it would drop the authored
  page out of `recall`. Pointer truncation now lands on a word boundary.
  Upgrading does not clean up after the old behaviour. A pointer memory
  that already carries `wiki.claim_events` rows from before this fix is
  still a synthesis candidate, because `wiki_synthesize` selects from
  `claim_events` and never reads `memories`. Re-running `wiki_extract`
  will not clear those rows: its pointer exclusion applies on every
  branch, including `force` and an explicit `memory_id`, so the
  `delete_claims_for_memory` call inside it is now unreachable for a
  pointer. The only in-product path that still deletes them is `forget`,
  which removes the memory itself and so drops the authored page out of
  `recall` — the outcome #622 rules out. Clearing the rows while keeping
  the pointer is therefore a manual, one-time statement against the
  store:
  `DELETE FROM wiki.claim_events WHERE memory_id IN (SELECT id FROM memories WHERE source LIKE 'wiki://%');`
  On SQLite the table is `wiki_claim_events`; the rest is identical. Any
  page already derived from such a memory is removed with `wiki_purge`,
  which now reaches every page kind.
- `wiki_purge` reaches every page kind (#622). Its page-kind directory
  set was a hand-kept copy that had drifted from `shared.wiki_layout`, so
  pages under `rfc/`, `explanation/`, `how-to/`, `runbook/`, `tutorial/`
  and `files/` were skipped in silence and had to be deleted by hand. It
  now derives from `PAGE_KINDS`, and the result reports
  `wiki_pages_total`, `unscanned`, `errored` and `unrecognised_dirs`
  alongside `scanned` so a caller can tell a full sweep from a partial
  one. A page that failed to read counts as scanned, not unscanned: an
  I/O fault no longer hides inside the coverage gap.

### Changed

- **Codex exposes the full tool profile and registers all 11 lifecycle hooks.**
  Host payloads and timeout limits still affect behavior; see
  [Codex hook limitations](docs/codex-plugin.md). The Codex
  plugin now serves the complete tool profile (`.mcp.json` drops
  `--profile lean`, matching the Claude manifest's server args, which carry
  no `--profile` flag) and installs the same 11 lifecycle hooks through
  a new `plugins/hypermnesia-mcp-codex/hooks/hooks.json`, referenced from
  `.codex-plugin/plugin.json` by path the way `mcpServers` already is. Each
  hook runs `uvx --from "hypermnesia-mcp[postgresql,sqlite]"
  hypermnesia-mcp-hook <module>`, the console script added in #605, so the
  package still ships only its own directory, never this repository and never
  `scripts/launcher.py`. Event names are Codex's own: `compaction_checkpoint`
  moves to `PreCompact` because Codex has no `Notification` event, and
  `SessionEnd` takes Codex's documented 3-second maximum instead of the
  Claude manifest's 30. Every other hook carries the Claude manifest's own
  timeout, because a latency budget is part of behaviour: unset, Codex would
  let a stalled `UserPromptSubmit` hook hold a prompt for its 600-second
  default where Claude Code caps the same hook at 5 seconds. The two
  `PreToolUse` gates declare none on either host, which is the parity case.
  Matchers carry Codex's native tool names
  (`apply_patch`, `exec_command`, `shell_command`) alongside Claude's, so the
  translations in `host_event.py` (#608) actually receive the events they
  translate. This reverses the earlier "Codex is additive, reduced" design.

## [4.23.1] - 2026-09-22

### Fixed

- Team decisions retain their project scope (#611, ADR-1083). #604/ADR-1080
  (4.23.0) stopped a session from receiving another project's hot and
  protected memories, but a deliberate decision written under an agent
  context was still marked `is_global`, so it kept crossing project
  boundaries by that separate path. A new `is_team_decision` marker grants
  visibility across a project's own agents without setting `is_global`.
  SessionStart and agent briefings enforce project scope on both markers,
  ingestion preserves the directory, and initialization no longer promotes
  a team decision to global scope. A dry-run-first reclassification script
  narrows existing global rows to the ones the old promotion actually
  produced; every other global row, including one the script cannot
  explain, is left alone and reported, not cleared.

## [4.23.0] - 2026-09-17

### Added

- **A session's tool sequence and turn count come from a Codex rollout too
  (ADR-1081, #610).** `infrastructure/transcript_activity.py` read only
  Claude Code's `{"type": "assistant", ...}` transcript shape, so a Codex
  SessionEnd fed `mine_skills` nothing: a Codex rollout's tool calls are
  `response_item` records of payload type `function_call` or
  `custom_tool_call`, not `assistant` message content, and the reader
  matched none of them. `transcript_activity` now peeks a transcript's
  first record — `type == "session_meta"` routes to a new
  `infrastructure/transcript_rollout.rollout_activity`, everything else
  routes unchanged to the existing Claude reader — and the rollout reader
  yields the same two fields in file order, repetitions included, capped
  at the same `MAX_TOOL_SEQUENCE`.

- **Codex hook events normalise into what the lifecycle hooks already read
  (#608).** `hypermnesia-mcp-hook` (#605) ran a hook module unchanged
  against whatever stdin carried, so a Codex `apply_patch` or
  `exec_command`/`shell_command` event reached `decision_gate`,
  `preemptive_context`, `pipeline_impact_bump` and the rest in a shape none
  of them read `tool_name` or `tool_input` for. `mcp_server/hooks/host_event.py`
  now normalises one host event into the Claude-shaped event(s) each module
  already reads before `entry.py` dispatches: `apply_patch` expands into
  one Edit/Write event per file operation via the new fail-closed
  `mcp_server/hooks/host_patch.py` parser (ported from the same owner's
  zetetic-team-subagents `hooks/lib/host_events.py`, MIT licensed);
  `exec_command`/`shell_command` become a `Bash` event with `workdir`
  resolved against `cwd`; `SubagentStart` maps `agent_type` to
  `agent_name`. A Claude Code event passes through byte-identical. A patch
  that cannot be translated without losing edit information is refused,
  matching how `decision_gate`/`no_deps_gate` already fail closed: exit 2
  on a `PreToolUse` event, exit 1 with a stderr line otherwise.

- **A console entry point runs any Cortex lifecycle hook from the installed
  wheel (#605).** A Codex plugin ships only its own directory, so it cannot
  reach this repository's `scripts/launcher.py` the way the Claude Code
  plugin does. `hypermnesia-mcp-hook`, a new `[project.scripts]` entry
  backed by `mcp_server/hooks/entry.py`, validates its module argument
  against the eleven hook names `.claude-plugin/plugin.json` wires,
  resolves the storage backend the same way the server does, wires the
  composition root the same way `scripts/launcher.py` does, and dispatches
  to the named hook's own `__main__` unchanged. A Codex plugin can then call
  `uvx --from "hypermnesia-mcp[postgresql,sqlite]" hypermnesia-mcp-hook
  <module>` directly. This changes nothing for the Claude Code plugin,
  which keeps using `scripts/launcher.py`.

- **The host-contract verifier counts the tools the server registers
  (ADR-1077).** `scripts/verify_mcp_hosts.py` held its own floor of 52 with a
  ceiling three above, so it stayed right through the move to 54 (ADR-1066)
  and only failed when the prediction tools took the count to 57, blocking two
  CI jobs on a number nothing had updated. `mcp_server/tool_surface.py` now
  reads the surface from the registry modules and the verifier derives its
  bounds from it, with a test pinning both against what `register_all`
  actually registers. The review of that fix found three more copies, all
  older than it: `.bestpractices.json` named the pinned test at 52 inside an
  identifier, where the claim regex could not see it; `.claude-plugin/
  marketplace.json` advertised 50 tools to every install and was scanned by
  nothing; and the docker-smoke floor was a bare literal. The first two are
  corrected and now gate-checked, the marketplace one by a targeted check
  because that same field also recounts the plugin's version history, and the
  third is pinned by a test.

- **Prediction records, and a score for the confidences they carry (#597).**
  Cortex stored what happened and never what was expected, so nothing it held
  could turn out wrong in a way it noticed: 796 procedural skills mined from
  the maintainer's transcripts all sit at proficiency 0.5 because no session
  records an outcome. Three tools now close that loop. `predict` writes a
  falsifiable prediction with the confidence held before the outcome is known;
  `resolve_prediction` settles it against an observation, naming the verdict,
  the kind of source that decided it and a reference to that source; and
  `calibration` returns the mean squared distance between confidence and
  outcome, the scale most contemporary writing calls the Brier score (Brier's
  1950 paper reports twice it), with the 0.25 a constant 0.5 forecast earns
  and the per-band frequencies the mean cannot show. Cortex never
  fetches the evidence and knows nothing about any forge or review
  convention, which is what makes the contract work in any repository
  (ADR-1076). The table lives on both backends. Standalone tool count 54 to
  57, 60 with both upstream integrations.

- **The Path B draft tools are exposed over MCP (#579).** `wiki_get_draft`
  and `wiki_refine_draft` had existed as handlers since ADR-0467 without ever
  being registered, so no client could call them and `wiki_get_draft`'s own
  instructions named a tool `tools/list` never advertised. They now register
  from `mcp_server/tool_registry_wiki_drafts.py`, a module of their own so
  `tool_registry_wiki.py` stays inside the 300-line cap (ADR-1066): reading a
  draft is read-only, submitting refined prose is a non-idempotent write, and
  both are interactive-class. The standalone tool count moves from 52 to 54
  (57 with both upstream integrations).

### Fixed

- **SessionEnd writes its session-log row before it consolidates, not
  after (ADR-1082, #610).** `hooks/session_lifecycle.py` ran
  `asyncio.run(consolidate_handler(...))` in-process after the log write,
  which cost nothing extra under Claude Code (SessionEnd has no enforced
  timeout there) but risked the whole hook under Codex, where SessionEnd
  has a 1 s soft / 3 s hard timeout well under a consolidation cycle's
  cost. Consolidation now runs in a detached subprocess that relaunches
  `session_lifecycle` with `--consolidate <mode>` (`Popen`,
  `start_new_session=True`, not waited on), spawned
  after the log write, at the same light/standard/full depth the turn
  count already gated it to.

- **Session-start and per-prompt injection stay inside the session's project
  (#604).** `auto_recall` and `session_start` queried memories with no
  project predicate, so a session under one project received the hot and
  protected memories of every other project the store held. Both hooks now
  apply one rule, shared across the PostgreSQL and SQLite paths
  (`mcp_server/shared/project_scope.py`, ADR-1080): a memory is injected
  when it is global, or its `directory_context` is the session's project
  root or an ancestor of it. An empty `directory_context` is not a
  wildcard. The project root comes from `CLAUDE_PROJECT_ROOT` or the hook
  event's `cwd`; when neither is available the hook logs that it could not
  resolve one and injects globals only, never everything. The predicate
  runs inside the query, before the existing heat-ordered `LIMIT`, on both
  backends: applied after the fetch instead, foreign-project rows above
  the heat floor would consume the limited candidate window and starve a
  project's own rows out of it. Team decisions stay global by design and
  are unaffected. The `recall` tool's own behaviour is unchanged.
  Migration consequence: a memory written before this fix with an empty
  `directory_context` and `is_global = FALSE` stops being injected by
  these two hooks on both backends; it stays reachable through the
  `recall` tool and can be re-scoped or promoted to global.

- **Claude and direct MCP startup honour the same saved backend (#600).** A
  saved SQLite selection was honoured by the Claude launcher while direct
  console/module startup could select a reachable PostgreSQL server, sending
  the two hosts to different stores. Direct startup now resolves the saved
  selection before loading memory settings, preserving explicit overrides.
  Existing databases are not migrated or merged.

- **Report worktrees outside the repository host directories (#602, ADR-1079).**
  Anchor the `.Codex/` ignore rule to the repository root. The optional
  doctor check accepts `.Codex/worktrees/` and `.claude/worktrees/`, using
  the main checkout as its root even when called from a linked checkout.
  Outside worktrees produce a warning without changing the exit code.
  NUL-delimited Git output preserves newlines and spaces in their paths.
  Failed Git invocations produce an optional warning with a retry command.
  A project with no Git repository at all is an ordinary condition, not a
  failure to inspect, so a stdlib `.git` walk now tells that case apart
  from Git being unavailable or timing out before the check ever shells
  out: `ok True, detail "not a git checkout"` on the former, the warning
  kept for the latter.

- **Procedural skills are stored on the default backend too (#596).** The
  `procedural_skills` table existed only on PostgreSQL, so on SQLite the
  session-end writer mined its skills and lost every one to an
  `AttributeError` its caller swallowed, leaving `recall_skills` permanently
  empty on the backend plugin installs use. SQLite gets the table and the two
  operations, mirroring the PostgreSQL columns (ADR-1075); an existing
  database picks the table up on its next open. Proficiency still sits at 0.5
  for every skill: nothing records a session outcome yet (#597).

- **One transcript reader, and it refuses a non-path (#591 follow-up).**
  `scanner.iter_tool_uses` streamed the same assistant `tool_use` blocks as
  `infrastructure/transcript_activity.py` and had no caller anywhere in the
  repository; it carried the two crashes the review of #592 closed in the new
  module. It is deleted. `transcript_activity` now returns its empty result
  for a `transcript_path` that is neither text nor a path, where it raised
  `TypeError`: the value comes from the hook event's untyped JSON envelope and
  runs in a path with no exception handler (ADR-1073).
- **A slow runner no longer turns `main` red (#594).** The `Test (SQLite
  backend)` job's `timeout-minutes: 10` left 1.7x headroom over its measured
  p90, and two runs of 2026-09-16 exceeded it: `main` at `a981f935` (cancelled
  at 616 s, 74 % of the suite) and PR #584's first attempt (610 s). Both passed
  on a rerun, in 416 s and 276 s. Measured over that day's 21 job executions,
  every attempt counted: 18 successes from 234 s to 416 s, median 328 s, p90
  348 s, and three non-successes, the two timeouts plus a 47 s cancellation
  from a superseded push. The budget is now 20 minutes, 3.4x that p90 and
  about twice the point where both timeouts fired, with the measurement
  recorded beside the number (ADR-1074).

- **Procedural learning finally has an input (#591).** Every session entry was
  written with `toolsUsed: []` and `turnCount: 0`, because the SessionEnd
  payload carries neither and `hooks/session_lifecycle.py` read them from it:
  413 of 413 entries in the live log, so `procedural_skills` held 0 rows and
  `recall_skills` always returned nothing. The entry is now filled from the
  session's own transcript, in call order with repetitions, which is what
  `mine_skills` reads (`infrastructure/transcript_activity.py`, ADR-1072). The
  scanner's import path kept tool names in a set built from a head-and-tail
  sample; it now takes the ordered sequence from the whole file. Measured over
  374 transcripts: 206 carry a sequence, mining returns 796 skills in 0.02 s,
  and a session end reads one transcript in about 4.5 ms. Proficiency stays at
  0.5 until sessions record an outcome.

- **The launcher installs from an interpreter that has no pip (#582).**
  Every install ran `sys.executable -m pip`, so from a `uv venv` (no pip module
  by design) the plugin's private `deps/` directory could not be filled at all:
  `[cortex-launcher] dependency install failed: <python>: No module named pip`.
  `launcher_pip.pip_entry()` now resolves the installed module first, then the
  pip wheel the standard library bundles for `ensurepip`, run in place from the
  wheel so nothing is installed into the interpreter, and otherwise raises an
  error naming that interpreter (ADR-1067). Measured on a `uv venv`, Python
  3.13.7: the 12 installer tests pass where 11 errored in setup.
- **A wiki draft refinement carrying no content is refused (#583).**
  `wiki_refine_draft` accepted a call with nothing but a `draft_id`: it stamped
  the draft's `synth_model` and wrote a `refined_llm` memo recording a
  refinement that never happened. Such a call now returns an error and writes
  neither the draft nor the memo (ADR-1068).
- **A wiki draft refinement carrying an empty value is refused (#585).** The
  ADR-1068 refusal tested `is None`, so `lead: ""`, `title: "   "`,
  `sections: []` and `frontmatter: {}` were written over the draft: a blanked
  lead reads as a placeholder to the curator, which subtracts 0.25 from the
  draft's score, and an empty frontmatter drops the synthesizer's `updated`
  stamp. The handler now refuses the call and names every field whose value is
  empty (ADR-1069).
- **A draft section must carry a heading and a body, both text (#587).**
  `_validate_against_contract` checked the kind's required headings and each
  section's body, never a section's own heading, so for a kind with no required
  section a heading of `"   "`, or a section with no heading key at all, was
  written to the draft, where `wiki_compile` mirrors it into `wiki.pages.sections`
  under an empty key (the published Markdown drops it). The nested
  `required: [heading, body]` of the tool schema is documentation: the
  client-visible schema comes from the registered wrapper's signature. Both
  fields are now validated as non-blank text, and a number for either returns a
  validation error instead of raising `AttributeError` (ADR-1070).
- **The wiki.pages mirror holds what the page holds (#589).** The Markdown
  renderer dropped a section with no heading while `handlers/wiki_compile.py`
  mirrored it into `wiki.pages.sections` under an empty key, so a file and its
  row described the same page differently, and `core/draft_curator.py` raised
  `AttributeError` on a heading that was not text. The four readings of a
  section now come from one place, `mcp_server/shared/wiki_sections.py`, and
  `wiki_refine_draft` also refuses two sections carrying the same heading,
  which the mirror's mapping silently deduped (ADR-1071).
- **Refining a wiki draft no longer raises its confidence (#578).**
  `handler_refine` (`mcp_server/handlers/wiki_refine.py`) wrote a fixed 0.85
  into every refined draft and its `refined_llm` memo, which put the draft past
  the curator's 0.6 approve threshold whatever the confidence of its source
  claims. A refined draft now keeps the confidence the synthesizer derived from
  its claims, and the memo records that value (ADR-1065). The handler is not
  registered as an MCP tool, so no draft reached the overwrite through the
  server.

- **An installer upgrade leaves one version of each package in `deps/` (#573).**
  `scripts/setup.sh` (the `--postgres` path of `install-plugin.sh`) and
  `scripts/setup.py` ran `pip install --target` straight into the persistent
  deps directory. pip skipped every package directory that already existed but
  still added the new `*.dist-info`, so the 4.21.0 → 4.22.0 upgrade kept
  sentence-transformers 5.6.1 code under 6.0.1 metadata and failed verification
  on tokenizers. Both installers now go through the launcher's scratch-and-commit
  install (`python3 scripts/launcher_deps.py --requirement FILE DEPS_DIR`), under
  the launcher's lock, which replaces changed entries and prunes superseded
  `*.dist-info` (ADR-1063). A distribution with several `*.dist-info` is no
  longer read as satisfied, so re-running `install-plugin.sh` also repairs a
  directory an earlier upgrade left mixed.
- **Re-running an install on an up-to-date `deps/` replaces nothing (#575).**
  The launcher's idempotence guard found an entry's distribution from the
  entry's name, so every entry named differently from its distribution was
  replaced on every install: `yaml`, `sklearn`, `google`, `bin`, the shared
  `__pycache__`, and so on. On a clone of a 4.22.0 deps directory that was 27 of
  213 entries, with 977 `.pyc` files rewritten. The guard now reads each entry's
  owners from the scratch install's `RECORD` files and skips the entry when
  every owner is already at the resolved version (ADR-1064). The same clone now
  comes out byte-identical. An entry deleted from `deps/` while its metadata
  stays at the pin is now restored instead of skipped.

## [4.22.0] - 2026-09-15

### Fixed

- **Every handler parameter is reachable over MCP (#559).** The client-visible
  schema of a tool is derived from its hand-written wrapper in
  `mcp_server/tool_registry_*.py`, and 13 of 54 wrappers had drifted from their
  handler's `inputSchema`. `recall` dropped `tags_any`, `tags_all`,
  `include_low_signal`, `cross_domain` and `sa_mode`, so the host protocol's
  `recall(tags_any=["archival"])` could not be called. `remember` dropped
  `is_global`, `created_at` and `initial_heat`, so the remember-global skill's
  `is_global: true` never reached the handler. The same gap affected `anchor`,
  `consolidate`, `curate_wiki`, `get_causal_chain`, `ingest_codebase`,
  `rate_memory`, `recall_hierarchical`, `unified_search`, `validate_memory`
  and `wiki_purge`. `tests_py/handlers/test_tool_schema_parity.py` now asserts
  exact equality, in both directions, for every tool of a server built with
  every upstream gate open. `wiki_write`'s `title`, `summary` and `body`, which
  the handler never read, are removed from its contract.

- **Decisions written under an agent context reach Team Decisions (#561).**
  ADR-0200's rule (a decision stored with an agent topic is marked
  `is_global`) ran only in `core/memory_ingest.py`, which only benchmarks and
  tests call. On the live store, 233 current protected agent-scoped rows were
  local and 1 was global, so the SessionStart block and the subagent briefing
  almost never found one. `core/team_scope.py` now applies the rule on the
  `remember` path, for deliberate writes from a trusted origin only (a fetched
  page or an automatic capture carrying a decision cue does not propagate). A
  one-shot, idempotent backfill applies the same rule to rows stored before the
  fix; on the maintainer's store it matched 131 rows.

- **`core/` performs no I/O (#560).** The 17 modules under `mcp_server/core/`
  that imported `os` or `pathlib` no longer do. Environment flags
  (`CORTEX_ABLATE_*`, `CORTEX_DECAY_DISABLED`, `CORTEX_*_BETA`, ...), the
  FlashRank model cache and the wiki filesyste…43611 tokens truncated…the canonical writer would have broken the CAS guard and the decay clock needed by the J+30 re-measure).

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
  **Correction (2026-08-10, issue #347):** the `2f45bcb`/`0.8279`/`94.3%`
  figures above have no committed per-query artifact anywhere in this
  repository — `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/`
  was never added on any branch (`git log --all --diff-filter=A` confirms
  this). Current publication-facing documents (README, both arXiv papers)
  use the artifact-backed pair instead: `MRR = 0.8278`, `R@10 = 94.2%`,
  code SHA `ef178da7` — which is **before**, not after, the plasticity fix.
  This historical entry is left as originally written (it records what
  shipped in v3.15.0); do not treat it as a current figure.
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
