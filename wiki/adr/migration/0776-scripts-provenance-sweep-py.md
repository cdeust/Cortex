# ADR-0776: scripts/provenance_sweep.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/provenance_sweep.py`; original SHA-256 `672bda1f1d8aa910316fbf1e2ad27f75a1b5db324fcfd961b93e61e6546cd9f9`.

## Original docstring, lines 2–38

````text
"""Full-corpus provenance sweep — I6-D6 grader run at scale (M-D5, 7.5).

The grader itself (``handlers/validate_memory.py``) already exists and is
the sole writer of ``memories.source_attribution``'s grade vocabulary
(verified/verifiable/unverifiable) — this script adds NOTHING new to the
grading logic. It is a thin, paginated driver: the corpus-wide pass the
I6-D6 design specified but that had never been run past a 100-row sample
(inc6.5) or the full store (§0.4 of the design doc: 72/10 079 graded).

Runs ``handlers.validate_memory.handler`` repeatedly, following its own
``after_id`` cursor (1000 rows/call) until ``next_after_id`` is ``None``,
and writes a campaign journal artifact: before/after grade distribution,
per-page counts, and a bounded sample of per-memory reports.

Usage
-----

Dry-run (default) — grade every memory and report, write nothing::

    uv run python scripts/provenance_sweep.py

Apply the change to the DB (NOT run by this increment's author — the
orchestrator decides, per the 7.5 task mandate)::

    uv run python scripts/provenance_sweep.py --apply

The pass is idempotent by construction (validate_memory.py's own
contract, i6d6): re-running after ``--apply`` re-computes the same grade
for a memory whose references haven't changed and writes the identical
value — zero DB deltas on a stable corpus, confirmed per-memory in
``tests_py/handlers/test_validate_memory.py::TestProvenanceIdempotence``.

Network bound: ``--url-check-limit`` caps DISTINCT URLs HEAD-checked PER
PAGE (default 0 for this driver — see the module docstring's rationale;
override for a network-connected run). URLs beyond the limit are graded
"not sampled this pass" (ceiling verifiable, never penalized as dead).
"""
````

## Original comment, lines 58–59

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 126–128

````text
# Reclassification transitions are read from the CURRENT (not
            # yet mutated on dry-run) DB row via the report's memory_id —
            # cheap because reports already carry the field we need.
````

