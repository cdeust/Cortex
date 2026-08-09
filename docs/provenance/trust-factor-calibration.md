# Trust-factor calibration sweep (issue #368) — pre-registration

Pre-registered **before** the expensive arms were run, per
`docs/provenance/verification-protocol.md` (Fisher discipline: the design and
the decision rule are fixed in advance, so the chosen value cannot be a
post-hoc pick from the results table).

## Quantity under calibration

`UNTRUSTED_ORIGIN_FACTOR` (W) in `mcp_server/core/retrieval_dispatch.py` — the
multiplier applied to a candidate whose `capture_origin` is not in
`_ORIGINS_TRUSTED_AT_READ`. Applied in the ranking expression before
`ORDER BY` and before the top-N cut, on both backends.

W = 1.0 is the identity (no demotion) and is the shipped value until this
sweep reports.

## Decision rule (fixed in advance)

> **Choose the LARGEST W that defends 4/4 adversarial scenarios while every
> gated floor still holds.**

Largest, not smallest: W is a distortion of the relevance ranking, so the
weakest demotion that still does the job is the one that costs least. A
smaller W that also passes would trade relevance for no additional security.

If no W satisfies both, the result is reported as a conflict and escalated —
not resolved by relaxing a floor.

## Gates (authority: `benchmarks/reproduce.sh`, not the prose in CLAUDE.md)

| Floor | Value |
|---|---|
| `FLOOR_LME_R10` | 0.982 |
| `FLOOR_LME_MRR` | 0.914 |
| `FLOOR_LOCOMO_R10` | 0.915 |
| `FLOOR_LOCOMO_MRR` | 0.805 |
| `FLOOR_TOLERANCE` | 0.005 |

BEAM-100K is measured and reported but **not gated** — `reproduce.sh` excludes
it deliberately ("its published proxy numbers predate the 200→395-question
split re-basing"). An earlier draft of this work cited a BEAM ≥ 0.543 gate
taken from a comment in `pg_schema.py`; that is not the applied gate, and the
file above is the authority.

## Grid

Chosen from the cheap criterion, not arbitrarily. The adversarial corpus was
swept first (SQLite, in-memory, seconds per point), giving a sharp transition:

| W | scenarios defended |
|---|---|
| 1.0 | 0/4 |
| 0.95 – 0.80 | 2/4 |
| 0.70 – 0.20 | 4/4 |

So the expensive arms bracket the 0.8 → 0.7 transition rather than sampling
uniformly:

`W ∈ {1.0 (baseline/identity), 0.8, 0.7, 0.6, 0.5}`

The 1.0 cell is the control arm: it must reproduce the pre-#368 numbers, and
any drift in it invalidates the comparison rather than the treatment.

## Protocol

- One `benchmarks/reproduce.sh` invocation per cell, **sequential**, each
  against its own ephemeral pgvector container (no shared state between
  cells, no parallelism — a 2026-08-08 fan-out saturated this machine).
- W is varied through `CORTEX_UNTRUSTED_ORIGIN_FACTOR`, read at import in
  `retrieval_dispatch.py` (same mechanism as `CORTEX_DECAY_LAMBDA` in
  `thermodynamics.py`), so each cell is a fresh process that picks the value
  up cleanly.
- Consolidation is ON. A consolidation-OFF run scores ≈0% on LME/LoCoMo — a
  known harness artefact (memory 4253160), not a regression, and the
  published floors are only reproducible with it.
- All three suites per cell: `longmemeval`, `locomo`, `beam`.

## Outputs

- `benchmarks/results/trust-factor-sweep/<timestamp>/cell_W<value>/` — the
  per-cell `reproduce.sh` results directory and MANIFEST.
- A summary table appended to this file once every cell has reported, with
  the chosen W and the arithmetic of the decision rule applied to it.

**This file is the source for the constant.** A W in the code without a row in
the table below is an invented constant and blocks review (§8).

## Results

_Pending — cells run after this pre-registration was committed._
