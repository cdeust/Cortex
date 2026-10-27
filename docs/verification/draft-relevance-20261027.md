# Draft relevance audit — 2026-10-27

Audited checkout: `.claude/worktrees/codex-drafts-current-main`, branch
`codex-drafts-current-main`, Codex session `01a17d21-9d79-7683-a0a8-eb42c4777763`.
Coordinator owns worktree registration and publication. No GitHub comment, closure,
merge, source-branch rewrite, or graph regeneration was performed.

## Source baseline and method

Fetched `origin/main` repeatedly during the audit. Each read resolved to
`b207d8c007553eb706ad3eb3aaccc1d89bafa9a2`; `HEAD` and
`git merge-base HEAD origin/main` initially matched that SHA. This is the PR803
merge. Main's success was context, not evidence that the drafts were delivered.

Read all four PR bodies, every issue comment (774:12, 771:12, 770:10, 646:5),
reviews and review threads (all empty), linked issues 703/704/705 and their
comments (empty). Fetched each PR head into a separate read-only audit ref.
Compared the original product change with current source, not the entire diff
of a stale branch that has since merged older main commits.

| Draft | Exact audited remote head | Verdict | Disposition |
|---|---|---|---|
| [774](https://github.com/cdeust/Cortex/pull/774) | `2f2633b5ea0cb2bc59feb78e5fc88adcf4b58736` | Stale snapshot; current consumer not established | Preserve draft/branch under owner no-close hold; no regeneration |
| [771](https://github.com/cdeust/Cortex/pull/771) | `fb2eeafdccb0a86e7e1bdebe8ee2ee7fbf540c17` | Pipeline-binary residual remains | Deliver separate residual fix; preserve draft/branch under no-close hold |
| [770](https://github.com/cdeust/Cortex/pull/770) | `d2bb5cb462a8dbee6860545a7d815742d494d5a2` | Backend-resolution residual remains | Deliver separate residual fix; preserve draft/branch under no-close hold |
| [646](https://github.com/cdeust/Cortex/pull/646) | `a0531d33889299e67963322b32c0717c502eeeda` | Held experiment; no evidence authorizes promotion | Preserve draft and branch `exp/sqlite-score-fusion`; do not merge or close |

## 774 — snapshot without an established current consumer

Primary artifacts at the exact old head:

- `.ua/meta.json`: `gitCommitHash=df3a4479fbd0207de6e0bade919f4de09da4273e`,
  `lastAnalyzedAt=2026-10-20T13:17:31Z`, `analyzedFiles=4197`.
- Decompressed `.ua/knowledge-graph.json.gz` successfully as JSON: 23,852 nodes,
  63,592 edges. This checks the actual graph artifact, not only its README.
- `.ua/README.md`: manual `gunzip -k` then external `/understand-dashboard`;
  overlays explicitly tied to PR770–773 and base `df3a447`.
- Owner comment 6327770303 requires truthful source SHA and explicitly says
  "Do not merge or close this PR." The coordinator reaffirmed that owner hold
  (msg_0113b44d2aec): the general maintenance request does not lift it. No current
  consumer or acceptance criterion authorizes regeneration.

`git rev-list --count df3a4479..origin/main` returns 28. Source delta includes
managed PostgreSQL (#748), redaction/erasure (#775), and current PR803 fixes.
`git grep -n -i -E 'understand.anything|knowledge-graph[.]json|[.]ua/' origin/main`
found no matches in the tracked main tree. `git log --all -- .ua` points to
the draft's artifact/tooling commits. The external dashboard named in the draft
is a possible manual viewer, not evidence of a current product dependency.
No claim is made that an external user could not consume the archived snapshot.

Validated the exact old-head artifacts without checking out or changing the branch:
22 Python scripts parse as AST; every tracked shell script passes `bash -n`;
23,852 graph node IDs are unique and all 63,592 edge endpoints resolve (zero
dangling edges). `link_sql_dataflow.py` derives ROOT from
`Path(__file__).resolve().parents[2]`; `run_probe.sh` derives paths from
`BASH_SOURCE[0]`; neither script retains `/home/user/Cortex`.
`.ua/.gitignore` includes `probe/home.*/`. These are syntax, structure and path
checks, not a fresh coverage scorecard, dashboard execution or native review.
The historical probe has sleeps/time limits; it was read, not executed.

Proposed coordinator hold text:

> Preserve draft774 and chore/understand-anything-graph under the explicit
> no-merge/no-close owner instruction in comment6327770303. The existing artifact
> still truthfully describes df3a4479; syntax, structural integrity and portable
> path corrections were checked. Current consumption and freshness acceptance
> remain unestablished, so do not relabel or regenerate it. Native reviews and
> runtime dashboard acceptance remain outstanding.

## 771 — pipeline installation still reachable from SessionStart

Original fix is commit `41fc50ef28c02b38ad4bdc9fa6359cd2af45c2c4`; later draft
heads merged older main. On audited main:

- `mcp_server/hooks/session_start.py` calls `_auto_wire_pipeline`;
  `session_start_background.py` calls `ensure_pipeline_connection`.
- `mcp_server/infrastructure/pipeline_discovery.py:206-211` imports and calls
  `install_pipeline()` when discovery fails. PR759's dependency work
  (`4a97ce16`) did not remove this separate product-binary download path.
- `scripts/setup.sh:364-406` already explicitly installs and then wires it.
  `pipeline_installer.py` honors `CORTEX_AUTO_INSTALL_PIPELINE=0`.
- `PRIVACY.md` lacked this GitHub/Rust/crates.io transfer. The 46 MB figure
  comes from the owner-authored [issue705 audit](https://github.com/cdeust/Cortex/issues/705),
  not a new download measurement.

Rebuilt residual removes only discovery's installer call; existing registration,
stale-entry cleanup and explicit setup stay covered. Two regression cases
(absent configuration and stale configured binary) refuse any installer call.
No old wiki/ADR was copied: main uses ADR1111 for hard erasure; the old draft's
latest tree had already renamed its pipeline decision to ADR1116.

Owner comment [6327771709](https://github.com/cdeust/Cortex/pull/771#issuecomment-6327771709)
explicitly says "Do not merge or close this PR." The coordinator's current
instruction preserves that hold; the residual can be delivered separately.

Proposed coordinator wording:

> Preserve draft771 and fix/pipeline-install-out-of-hook under the explicit
> owner hold. Current-main regression proved the pipeline-binary part of issue705
> remains; the separate tested residual removes installation from discovery and
> discloses the explicit setup transfer. This audit neither closes issue705 nor
> certifies the old draft's native reviews.

## 770 — launcher policy still missing from wheel entry points

Original implementation `aa3a1fba3f71a8132c7f295a3b81f0dea0a56f0f`, followed by
the supplied-environment correction `89d151a7` and postcondition correction
`d2bb5cb4`, addresses [703](https://github.com/cdeust/Cortex/issues/703) and
part of [704](https://github.com/cdeust/Cortex/issues/704). On audited main:

- `scripts/launcher_backend.py` persists ADR1104's first-launch decision.
- `mcp_server/hooks/entry.py` still prepares an undecided backend and calls
  `resolve_auto_backend`, which constructs the shared store to decide.
- `mcp_server/__main__.py:25` applies saved-marker resolution, without the
  launcher's first-launch policy. A fresh subprocess demonstrably binds `auto`.
- `auto_recall.py` and `session_start_common.py` still synthesize local PG URLs.
- PR631 (`25a36819`) provided shared-factory resolution for hooks; PR748
  (`8b6aa72a`) added managed-marker attachment. Neither supplies the missing
  first-launch decision to direct wheel/server entry points.

Residual implementation moves the current launcher decision to infrastructure,
uses it before settings imports in all entry points, removes hook-local URL
defaults, and refuses PG helpers without a URL. Provisioning callers and tests
migrate with the moved policy. Retains managed-PG root exclusion, attachment,
explicit URL precedence, operator-selected `auto`, and the existing marker
provenance used by Setup to recognize an empty first-launch SQLite store.
Invalid markers and filesystem/managed-server failures end entry points with
`Cortex not ready`, exit 1.

Main ADR1110 is now redaction, not this draft's backend ADR. No colliding ADR,
wiki mirror or manifest edit is imported. No library-default removal is claimed:
`memory_config.DATABASE_URL` and direct library `auto` remain outside the
wheel-entry residual, so issue704 is not fully resolved.

Owner comment [6327772155](https://github.com/cdeust/Cortex/pull/770#issuecomment-6327772155)
explicitly says "Do not merge or close this PR." Preserve the old draft/branch;
submit current-main residual fixes separately.

Proposed coordinator wording:

> Preserve draft770 and fix/single-backend-resolution under the explicit owner
> hold. Current main still left fresh wheel hooks/server launches in auto
> resolution. The separate tested residual shares the current launcher's policy,
> preserves managed PostgreSQL and explicit settings, and verifies SQLite memory
> persistence through real MCP remember. The library portion of issue704 and the
> old draft's native reviews remain outside that evidence.

## 646 — owner hold remains binding

Owner comment [6327774005](https://github.com/cdeust/Cortex/pull/646#issuecomment-6327774005)
explicitly says retain draft, do not merge or close. Its primary committed
`benchmarks/results/sqlite_score_fusion/summary.json`, `all`, n=500, reports:

| Production reranker arm | RRF | Score fusion | Paired delta | 95% interval |
|---|---:|---:|---:|---|
| MRR | 0.8672984127 | 0.8587746032 | -0.0085238095 | [-0.0224092857, 0.0052620437] |
| Recall@10 | 0.952 | 0.934 | -0.018 | [-0.032, -0.006] |

Read the actual paired JSONL, analysis script and driver as well as the summary.
Parsed all 500 JSONL records, verified 500 distinct question IDs, and independently
recomputed the primary paired means: MRR -0.008523809523809524 and recall@10
-0.018, agreeing with the committed summary. These are historical experiment
results, not a fresh benchmark; they do not establish a quality improvement.

Current `sqlite_store_search.py`, `sqlite_store_recall.py` and
`sqlite_store_recall_signals.py` retain rank fusion and ADR1109's whole-boundary
tie handling, introduced by `21e3b926` (#760). Draft score fusion is not present.
`benchmarks/lib/bench_db.py` still eagerly imports `PgMemoryStore`, consistent
with `tests_py/benchmarks/test_lib_init_no_psycopg.py`; the draft's lazy-import
contract dispute therefore is not a defect requiring a product patch on main.
No experiment fixes, rebases, benchmarks or branch edits were performed.

Proposed coordinator hold text:

> Keep draft646 and exp/sqlite-score-fusion unchanged under the explicit owner
> do-not-merge/do-not-close instruction. The committed paired n500 result does
> not establish an improvement with the production reranker. Any continuation
> requires its own experiment acceptance criteria and owner authorization.

## Verification and completion ledger

Private `.venv`: native ARM Python3.13.7, installed from `uv.lock` using
`uv sync --python /opt/homebrew/opt/python@3.13/bin/python3.13 --locked
--no-default-groups --extra dev --extra postgresql --extra sqlite --extra codebase
--extra benchmarks --group lint`. Ruff is pinned to 0.17.1. The shared main venv
was inspected read-only and rejected by lock-parity preflight; it was not changed.

RED, before production edits, on b207d8c0 with only new acceptance tests:

```text
PYTHONPATH=. .venv/bin/python -m pytest tests_py/infrastructure/test_pipeline_discovery_no_install.py tests_py/hooks/test_entry_fresh_backend.py tests_py/test_shared_backend_bootstrap.py::test_no_marker_records_sqlite_before_settings_bind -q
E Failed: hook discovery attempted to install the pipeline [absent config]
E Failed: hook discovery attempted to install the pipeline [stale config]
E AssertionError: assert None == 'sqlite' [hook]
E AssertionError: assert 'auto' == 'sqlite' [MCP bootstrap]
4 failed in 1.38s
```

GREEN on the residual implementation:

```text
PYTHONPATH=. .venv/bin/python -m pytest --tb=short -q -p no:randomly tests_py/hooks tests_py/infrastructure/test_pipeline_discovery.py tests_py/infrastructure/test_pipeline_discovery_no_install.py tests_py/infrastructure/test_pipeline_discovery_anchor.py tests_py/infrastructure/test_backend_marker.py tests_py/infrastructure/test_backend_resolution.py tests_py/scripts/test_launcher_first_backend.py tests_py/scripts/test_launcher_backend.py tests_py/scripts/test_launcher_pg_selection.py tests_py/scripts/test_launcher_pg_provision.py tests_py/scripts/test_launcher_setup_repeat_fallback.py tests_py/test_shared_backend_bootstrap.py tests_py/infrastructure/test_managed_pg_attach.py tests_py/infrastructure/test_managed_pg_isolation.py
1032 passed, 2 skipped, 2 warnings, 13 subtests passed in 80.15s (0:01:20)

PYTHONPATH=. .venv/bin/python -m pytest --tb=short -q -p no:randomly tests_py/hooks/test_entry_fresh_backend.py tests_py/infrastructure/test_backend_resolution.py tests_py/infrastructure/test_pipeline_discovery_no_install.py tests_py/test_shared_backend_bootstrap.py tests_py/integration/test_fresh_mcp_sqlite.py
24 passed in 8.40s
```

The second run includes the four original regression cases and the final new
failure-path tests. Real stdio MCP initialization, `remember`, server shutdown,
persisted SQLite marker and stored row are asserted. Network/model downloads
are disabled; this proves memory persistence, not embedding quality. The two
suite warnings are Python3.13's existing fork-from-multithreaded-process warning
in `test_consolidate_background_exit`; two skipped tests remain unexecuted.
No retrieval algorithm or quality threshold changed; no new retrieval benchmark
or platform-install acceptance is claimed.

| Changed execution path | Asserting evidence |
|---|---|
| Missing pipeline, with absent/stale config; installed/configured binary behavior retained | `test_pipeline_discovery_no_install.py` (RED/GREEN) and discovery/anchor suites |
| Fresh hook/server default and marker creation before settings | `test_entry_fresh_backend.py`, `test_shared_backend_bootstrap.py` (RED/GREEN), real stdio integration |
| Explicit direct/namespaced URL, alias/backend and saved marker precedence | backend marker, backend resolution, entry parity and launcher backend suites |
| Operator-selected auto stays explicit | `test_explicit_auto_remains_an_operator_choice` |
| Earlier-state, every-address refusal/listener/unclear error, libpq environment paths | migrated `test_launcher_first_backend.py`; supplied-environment regression |
| Marker creation succeeds/logs or fails without guessing; invalid marker | first-backend, backend-resolution, direct bootstrap and hook startup failure tests |
| Managed marker/inherited server, startup failure and shared attachment | real supervisor/SCRAM `test_managed_pg_attach.py` and isolation tests; resolver attachment test |
| Setup eligibility, retained fallback cause and existing SQLite protection after policy move | launcher PG selection/provision/repeat-fallback suites |
| PG recall/setup helpers receive no resolved URL | `test_pg_helpers_do_nothing_without_a_resolved_url` |
| Hook error boundaries: marker, managed PG, filesystem error → one line/exit1 | parametrized `test_hook_startup_reports_resolution_failure_once`; direct bootstrap marker error |

Final static checks:

```text
.venv/bin/ruff check
All checks passed!
.venv/bin/python scripts/check_craftsmanship.py --base origin/main
Craftsmanship gate: OK
git diff --check
[exit 0, no output]
```

The whole-tree formatter initially exposed one unchanged quote-style violation
in `scripts/check_ci_gate_complete.py:159`. The coordinator explicitly transferred
ownership of that one line in the answer to the Orca question; the exact Ruff0.17.1
correction was applied without a semantic change. No other CI gate or workflow
line was edited.

Final test run after that last code edit used the full 1032-test command above,
plus `tests_py/integration/test_fresh_mcp_sqlite.py` and
`tests_py/scripts/test_check_ci_gate_complete.py`, with the same flags:

```text
1061 passed, 2 skipped, 2 warnings, 91 subtests passed in 85.52s (0:01:25)
.venv/bin/ruff check
All checks passed!
.venv/bin/ruff format --check
3820 files already formatted
.venv/bin/python scripts/check_craftsmanship.py --base origin/main
Craftsmanship gate: OK
git diff --check
[exit 0, no output]
```

The final fetch still resolved main to b207d8c0; there was no new source delta
requiring reassessment. The original four draft refs and branches were not
modified. Process inspection after tests found no surviving test/MCP process
owned by this checkout. No review clone, additional worktree or graph copy was
created. Disposable environment cleanup is reported to the coordinator after
commit; the worktree and its local commit must be retained until publication.

Native Claude `/code-review` and `/security-review` were not run by this Codex
worker. No review verdict, hosted CI success, mergeability or published replacement
head is claimed. The host forbids GitHub publication during this dispatch; the
coordinator receives the tested local commit for publication and review.
