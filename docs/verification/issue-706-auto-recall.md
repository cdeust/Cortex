# Issue 706: automatic recall and capture visibility

Approved issue: https://github.com/cdeust/Cortex/issues/706

## Source bindings

The pre-fix production source inspected for this change is
`3aef5b590c839a0b2a46267a20477785490f691c`.
The hook used FTS and cut to three results without cross-encoder reranking.
The tool handler used the shared FlashRank reranker but hid results carrying
any tag in LOW_SIGNAL_TAGS, including ordinary user tags.

Capture provenance is already persisted as capture_origin (ADR-0114).
The replacement filter uses local_action/network and the legacy system source
post_tool_capture; an explicit deliberate origin takes precedence.
Default recall reports low_signal_dropped for the retrieved candidate set.
include_low_signal=true retains capture_origin on returned capture rows.
Prospective injection applies the same provenance predicate.

## Automatic retrieval

The hook now merges scoped lexical and scoped hot candidate pools before
calling the injection reranker, using recall's existing model, content cap,
score blend and WRRF constant. The pool multiplier comes from MemorySettings,
rather than a new tuning constant. SQL/store predicates apply project/global
scope before each pool's LIMIT. Existing heat, stale, supersession and benchmark
exclusions remain active.

This is a budgeted candidate path, not the tool's neural vector-discovery path:
it avoids loading sentence-transformers in every prompt process.
The cross-encoder can inspect low-overlap candidates from the hot pool.
Only cached reranker weights are used in a hook. Absent, corrupt or failing
weights produce a degradation diagnostic and retain lexical retrieval.
The installed manifest's five-second hook budget is unchanged.

## Hosted verification contract

`.github/workflows/auto-recall-parity.yml` runs on hosted Ubuntu with read-only
repository permissions and no owner account authentication. It:

- overlays the behavioral tests onto the pinned pre-fix source and requires
  pytest exit 1, preserving the raw failure log;
- runs the proposed filtering, injection, scope and fallback tests;
- measures the pre-fix and proposed production paths on a fixed synthetic
  thirty-memory/thirty-query paraphrase fixture;
- starts a fresh hook process for every prompt and keeps tool retrieval warm;
- clones the same seeded SQLite database independently for both arms of each
  query so replay writes cannot benefit the opposite arm;
- requires real neural embeddings, sqlite-vec and FlashRank, with downloads
  completed before measured hook execution;
- records tool hits at three/ten, tool MRR, hook hits at three, latency, budget
  observations, source SHA, model identities/digest and fixture digest;
- requires the old hook to exhibit a quality gap and the proposed hook to
  match or exceed tool hits at three on this fixture.

Latency is an observation rather than a machine-load-dependent test verdict.
The benchmark includes per-query stdout and stderr and saves the before/after
JSON reports as the auto-recall-parity workflow artifact. This fixture is new
synthetic evidence; it is not the unavailable original October 10 audit corpus.
Hosted results must be inspected before claiming measured parity or budget
conformance. No candidate code was executed on the control Mac.


## PR 826 review correction

The correction preserves persisted SQLite source provenance and filters system
captures, stale rows, benchmarks and low-heat lexical rows before each hook
pool limit. Explicit deliberate origin retains precedence over a legacy source
marker. Protected eligible rows remain first after semantic ranking.

The injection path receives an explicit inference-failure result and retains
lexical behavior on model/cache/inference failure. Unlike the tool path, it
drops individual passages rejected by the existing ADR-0245 confidence gate.
That gate's 0.15 floor is a pre-existing hand-tuned engineering default; it is
not calibrated on this hook's corpus. Hosted measurements and negative cases
are required before asserting retrieval quality.

Hosted prior evidence at 9f06321: unit job 122802652141 reported 1 failed,
11164 passed, 26 skipped; the failure counted the workflow's duplicate
installation path. Parity job 122802575036 reported 32 failed and 7 passed on
prior sources, then 62 passed on proposed sources, then failed preflight
because neural embedding weights were absent. The correction calls the
synchronous pinned embedding download before encoding and reuses the existing
locked-install composite action. The workflow runs on PR events, avoiding
an indefinitely pinned failure requirement on main pushes.

The new review regression module asserts pre-limit capture/stale starvation,
SQLite legacy source projection, semantic abstention, explicit inference
failure, and degraded protected lexical order with diagnostics. Hosted results
on the final published SHA remain pending; these are acceptance gates, not
claimed passing results. Latency remains measured data, never a wall-clock
pass/fail verdict.

The hosted report also preserves three out-of-fixture negative prompts and
requires empty proposed-hook output for each; it requires positive tool hits
and rejects degraded proposed-hook diagnostics. These controls test abstention
on this fixture rather than establishing a globally calibrated cutoff.


## Correction acceptance ledger

| Path | External evidence or hosted gate |
| --- | --- |
| Python syntax and configured lint families | 17 edited Python texts parsed; static Ruff checks have zero findings before publication. No imports or tests executed on the Mac. |
| Deliberate tags and hidden capture count | test_recall_low_signal_filter.py; hosted before log above |
| SQLite legacy source | test_sqlite_recall_projects_legacy_source |
| Capture and stale pool starvation | test_ineligible_rows_do_not_spend_either_pool_limit, both pool queries |
| CE accept and abstain | test_real_injection_reranker_abstains_on_irrelevant_scores |
| Inference exception | test_inference_failure_is_explicit |
| Model absent, cache failure, load failure, inference failure | test_degraded_hook_retains_lexical_protected_order_and_diagnostic |
| Empty semantic result | test_loaded_hook_abstains_with_empty_semantic_result |
| Paraphrase candidate and unavailable hot pool | test_auto_recall_paraphrase.py |
| Scope, receipt and protected lexical ordering | test_sqlite_hook_scope.py and test_sqlite_hook_paths.py |
| Schema split and bounded ID retrieval | existing handler schema/response-budget tests in unit CI |
| Pinned model preflight and negative query controls | hosted parity workflow; results pending |
| Dependency installation | existing locked-install action; test_every_uv_sync_installs_the_lock_as_it_is |
| Size and source-decision rules | hosted check_craftsmanship.py --base origin/main; baseline only removes the two statically fixed entries |
| Final behavior, native security and code review | pending on the published correction SHA |

The original 30-positive fixture remains a small-corpus measurement; the
pre-limit starvation tests use more excluded rows than the configured pool.
Neither establishes recall completeness on a large corpus of eligible memories.
