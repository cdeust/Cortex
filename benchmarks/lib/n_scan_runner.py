"""DEPRECATED stub — superseded by ``benchmarks.lib.latency_runner``.

The synthetic-corpus N-scan harness was renamed to ``latency_runner``
because retrieval metrics on the synthetic corpus produced identical
scores for cortex_full vs cortex_flat at N>=10k (the corpus has no
thermodynamic structure for heat to discriminate). The harness is now
the latency-only sibling; claim-bearing E2 retrieval lives in
``e2_subsample_runner`` (real benchmark subsample) and
``e2_zipf_runner`` (Zipf access pattern). See module docstring of
``latency_runner`` and ``tasks/verification-protocol.md`` §E2 for
detail.

This stub re-exports the public surface so existing callers and any
in-flight processes (e.g. ``python -m benchmarks.lib.n_scan_runner``
already running) continue working without breakage.
"""

from __future__ import annotations

from benchmarks.lib.latency_runner import (  # noqa: F401
    CorpusItem,
    DEFAULT_DB_URL,
    LATENCY_ONLY,
    MIN_QUERIES,
    RESULTS_DIR,
    TEMPLATES_PATH,
    TrialResult,
    main,
    run_trial,
    synth_corpus,
)


if __name__ == "__main__":
    raise SystemExit(main())
