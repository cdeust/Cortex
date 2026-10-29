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

## Hosted failure evidence at 1bdf8c6

Unit job [122825144932](https://github.com/cdeust/Cortex/actions/runs/40690888981/job/122825144932)
reported 2 failed, 11193 passed and 26 skipped. Both failures are existing
ID-pagination tests: the schema split moved the settings lookup out of the
recall composition root. The correction passes the caller's resolved response
budget into ID retrieval. The tests and their size assertions remain unchanged.

Parity job [122825074731](https://github.com/cdeust/Cortex/actions/runs/40690888995/job/122825074731)
reported 2 hook hits at three versus 28 tool hits at three on 30 queries.
The model preflight completed; this is a retrieval-quality failure.
The 0.15 confidence floor remains unchanged. The hosted report now records raw
cross-encoder scores for every fixture query/passage pair and every negative
query/passage pair, using the same cached model and passage truncation.
These measurements distinguish absent candidates from rejected passages and
provide evidence for a subsequent correction without guessing a new cutoff.
Raw-score inference failure is an explicit error. All existing parity and
negative-query assertions remain in force. New hosted results are pending.


## Hosted measurement prerequisite at b2087d3

Parity job [122841349229](https://github.com/cdeust/Cortex/actions/runs/40695584656/job/122841349229)
stopped at the craftsmanship gate: fetch_by_id exceeded the function-size cap.
No before/after reports were produced on that head. The function's explanatory
docstring is shortened without changing retrieval, access scope or pagination.

PostgreSQL lexical discovery again uses the pre-fix 200-character query prefix;
semantic ranking still receives the full prompt. The hosted regression
test_long_prompt_keeps_lexical_prefix_and_full_semantic_query checks both inputs.
Scope-starvation coverage now exceeds the configured candidate windows.
The parity workflow includes the new PG test and watches its diagnostic module
and all hook regression files.

The positive/negative parity assertions and the existing abstention policy
remain unchanged. The next hosted run must finish raw-score measurement before
a calibrated policy can be selected. The earlier 2-versus-28 retrieval failure
is unresolved; syntax and structural text checks do not establish parity.


## PR 826 trust correction after 6245dff

Hosted [run 40701184713](https://github.com/cdeust/Cortex/actions/runs/40701184713)
completed the model preflight and measured 2 hook hits against 28 tool hits.
Artifact 12821218436 preserves the raw scores. The correct bread-culture
passage scores 0.000015304052794817835, below the unrelated kaon control's
highest score, 0.000017647756976657547. A lower absolute per-passage cutoff
alone cannot retain that positive and reject that negative. The current
injection policy and the positive/negative parity gates remain unchanged;
the retrieval-quality failure is unresolved.

The automatic hook now builds its origin predicate once from ADR-0114's
read-trust allowlist, excluding local tool captures. Explicit deliberate
origin still overrides the historical post_tool_capture source marker.
Unknown, null, empty and future origins cannot enter either backend's
automatic lexical or hot pool. This is deliberately stricter than explicit
tool recall's visibility policy, which continues to expose unknown memories.

Untrusted imports now become unknown-origin records unless trust_flags is
explicitly enabled. Trigger result projection also labels absent provenance
unknown instead of inventing legacy trust. Both backend lexical searches use
the original 200-character bound, while semantic ranking receives the full
prompt. The hosted trust tests cover the origin/source matrix, both PG SQL
predicates, SQLite prompt bounding and imported provenance.

These changes address trust and fallback defects; they do not establish
paraphrase parity. All executable verification remains on hosted CI.

## Hosted gate corrections after b8cbc97

The unit job [122890249146](https://github.com/cdeust/Cortex/actions/runs/40709377205/job/122890249146)
reported 12 failed, 11215 passed and 26 skipped. The failing automatic-injection
fixtures omitted capture_origin, so their rows defaulted to unknown and the
new allowlist excluded them. Those fixture INSERTs now explicitly identify
test-authored deliberate memories; assertions and production trust defaults
are unchanged.

The parity job [122890141226](https://github.com/cdeust/Cortex/actions/runs/40709377172/job/122890141226)
stopped at the infrastructure-to-core import in hook_capture_filter.py.
Origin constants and the existing read-trust set now live in shared, consumed
by both core policy functions and the infrastructure SQL predicate. The trust
truth table and explicit-recall behavior remain unchanged.

Static validation parses every changed Python source as data and checks the
shared module dependency direction. Hosted unit and parity results on the new
commit remain required. The previously measured 2-versus-28 paraphrase deficit
and positive/negative score overlap are unresolved; this correction only
unblocks the next hosted experiment and does not establish issue #706 acceptance.


## Hosted signal comparison after 7a4424d8

Hosted [parity run 40743111482](https://github.com/cdeust/Cortex/actions/runs/40743111482)
again measured 2 hook hits at three versus 28 tool hits at three, with 30 tool
hits at ten. Mean hook latency was 0.7047040609333332 seconds; the maximum was
0.7507068599999798 seconds, and no query exceeded the configured five-second
budget. These are observations on that runner, not latency guarantees.

[Artifact 12841005532](https://github.com/cdeust/Cortex/actions/runs/40743111482/artifacts/12841005532)
contains the raw pair scores. Cross-encoder-only ordering places the certificate
target at rank 30 and the bookkeeping target at rank 5. The bread-culture target
scores 0.00001264155980607029, while the unrelated kaon query's highest passage
scores 0.000014890589227434248. An absolute raw-score cutoff cannot keep that
positive while rejecting every kaon passage. Ranking and candidate discovery
must be evaluated as well as abstention; lowering the cutoff alone is not an
acceptance result.

The next hosted report adds embedding_cosine and embedding_rank to every
positive and negative query/passage pair. It uses the same scalar encoder as
fixture seeding and explicit recall, and the cosine implementation already used
by recall_pipeline.familiarity_triage. Missing vectors or a fallback encoder
fail this diagnostic explicitly. Existing model/revision and fixture identities
remain in the report. Encoding occurs after the timed hook/tool observations,
so this diagnostic does not change their measured windows.

This is an evidence collection change only. Production retrieval, the relevance
floor, trust predicates, fixture, and positive/negative acceptance assertions
are unchanged. No embedding cutoff is selected from unmeasured assumptions.
Hosted results for this change are pending; issue #706 remains unresolved.


## Semantic abstention after 83743ce6 (merged with main at 190c6f1b)

Hosted [parity run 40794598785](https://github.com/cdeust/Cortex/actions/runs/40794598785)
measured 2 hook hits at three against 28 tool hits. Its artifact settles the
cause. The expected passage's raw cross-encoder score is at most 4e-5 for 12 of
30 queries, three of them near 1e-5, while each negative control's best passage
scores 1.3e-5 to 1.5e-5. A relative measure fails as well: one positive's
top-to-median log gap is 0.03, a negative control's reaches 0.12. No absolute or
relative cross-encoder cutoff keeps the positives and rejects the controls.
Embedding cosine separates them: the lowest expected-passage cosine is 0.235,
the highest negative-control passage cosine 0.152, and the expected passage is
in the embedding top three for 29 of 30 queries.

The hook therefore needs the semantic signal the tool already fuses. Loading
sentence-transformers in the hook process measured 15.8 to 23.3 s on the
owner's Mac against the 5 s manifest budget. The pinned revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41` ships `onnx/model.onnx`
(sha256 `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452`)
and `tokenizer.json`; mean pooling and L2 normalisation over that export load
and encode in 0.45 to 0.6 s and agree with the stored engine vectors at
cosine 0.99999994 or better on every fixture memory and query.

Policy: the hook merges its scoped lexical and hot pools as before, reads the
candidates' stored vectors (neural or legacy-unstamped space only, ADR-0616),
and admits a candidate when its cosine with the prompt reaches
`INJECTION_SIMILARITY_FLOOR = 0.19`, inside the measured 0.152 to 0.235 gap,
or when its own cross-encoder score passes ADR-0245's 0.15 gate (the previous
rule, kept so a lexical match without a stored vector is still injectable).
The cross-encoder no longer vetoes a semantically admitted candidate.
Similarity order is the first stage; the cached cross-encoder reorders with
recall's existing blend. The floor is calibrated on 30 positive and 3 negative
prompts, not globally. A
missing ONNX export, a missing package or a load failure keeps the existing
lexical fallback with its degradation diagnostic. `download_model` fetches the
export with the embedding weights; the parity preflight fails if the hook
encoder disagrees with the engine below cosine 0.999.

Local measurement, macOS arm64, Python 3.13.7, locked dev/sqlite/codebase/
postgresql/lint environment, the same benchmark command as the workflow:

| Source | tool hits@3 | hook hits@3 | negatives empty | hook mean / max s |
| --- | ---: | ---: | --- | --- |
| prior `3aef5b59` (`--expect-gap`) | 28 | 2 | not asserted | 1.51 / 2.31 |
| PR head `64c52723` | 28 | 2 | yes | 1.77 / 3.87 |
| this correction | 28 | 29 | yes (3/3) | 1.89 / 3.23 |

Mac latency includes an external-volume interpreter start; the hosted runner
measured 0.81 s mean before this change. Latency is reported, not asserted.

Remaining gap: candidate discovery is still the lexical and hot pools. A
relevant memory that is neither lexically matched nor among the hottest scoped
rows is not considered; the 30-memory fixture fits in the hot pool and does not
measure that case.

### Corrections after b1525d9a

Hosted parity run 40847804130 stopped at the craftsmanship gate:
`[layer-violation] mcp_server/core/injection_relevance.py: numpy`. Core may
import shared only. The core module now keeps the floor and the pure ordering
decision over a mapping of similarities; the cosine and vector decoding live in
`infrastructure/hook_query_encoder.py` as a `QueryScorer`, which the hook
obtains through `cached_query_scorer()`. The admission rule is unchanged.

The native Codex review of b1525d9a found that an installation whose semantic
job already recorded `ready` never re-runs it, so it would never fetch the ONNX
export. The job's record now names the model files it fetched
(`MODEL_FILES`, shared by `scripts/launcher_ml.py` and
`infrastructure/embedding_warmup.py` with a parity test); a ready record that
names other files, including every pre-upgrade record, counts as installing and
the next session starts the job again.
