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
calling the tool path's rerank_results, using its existing model, content cap,
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
