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

### Adversarial arm — how many scenarios each W defends

Re-measured, not carried over from §Grid: the table in that section was
prose with no committed artefact behind it, so half the decision rule rested
on a number nobody could reproduce. `benchmarks/lib/trust_factor_sweep.py`
now measures it over the same points (SQLite, in-memory, seconds per point;
same corpus and montage as `tests_py/infrastructure/test_sqlite_trust_ranking.py`).
A scenario counts as defended only when **both** memories are retrieved and
the legitimate one outranks the adversarial one — a demotion, not a filter.

| W | scenarios defended |
|---|---|
| 1.0 | 0/4 |
| 0.95 · 0.90 · 0.85 · 0.80 · 0.75 | 2/4 |
| 0.70 · 0.60 · 0.50 · 0.40 · 0.30 · 0.20 | 4/4 |

Data: `benchmarks/results/trust-factor-sweep/adversarial/adversarial-sweep.json`.
This **confirms** the §Grid table exactly, including the 0.80 → 0.70
transition the expensive grid was built to bracket. The largest W defending
4/4 is **0.70**.

### Gated arm — do the floors hold

One `reproduce.sh` per cell, sequential, own ephemeral pgvector container.
Sweep `benchmarks/results/trust-factor-sweep/20260809T085409Z/`, five cells,
all `rc=0`. Every cell reports `git_sha 66d2628f`, the same dataset sha256,
the same embedding-model revision, and `reranker_active: true` — one
provenance for the whole grid.

| W | LME R@10 (≥0.977) | LME MRR (≥0.909) | LoCoMo R@10 (≥0.910) | LoCoMo MRR (≥0.800) | 4 floors | BEAM MRR / R@10 (ungated) |
|---|---|---|---|---|---|---|
| 1.0 (control) | 0.9820 | 0.9178 | 0.9279 | 0.8158 | 4/4 PASS | 0.5156 / 0.7222 |
| 0.8 | 0.9820 | 0.9168 | 0.9374 | 0.8226 | 4/4 PASS | 0.5264 / 0.7175 |
| **0.7** | **0.9820** | **0.9178** | **0.9329** | **0.8181** | **4/4 PASS** | 0.5199 / 0.7100 |
| 0.6 | 0.9820 | 0.9178 | 0.9329 | 0.8175 | 4/4 PASS | 0.5342 / 0.7278 |
| 0.5 | 0.9820 | 0.9178 | 0.9369 | 0.8202 | 4/4 PASS | 0.5246 / 0.7094 |

Thresholds shown are `floor − FLOOR_TOLERANCE`; the applied test is
`got − floor >= −tol` (`reproduce.sh:376`). 20 floor checks, 20 PASS. The
control arm reproduces the published numbers exactly (LME R@10 0.9820,
delta +0.0000), so the comparison is valid rather than drifting.

### Decision

Both members of the rule are satisfied, so it applies without amendment:

- largest W defending 4/4 → **0.70** (0.75 and above defend only 2/4);
- at W = 0.70 all four gated floors hold, with margins +0.0000 / +0.0038 /
  +0.0179 / +0.0131.

**W = 0.7.** No floor was relaxed and no gate was reinterpreted to get there.

### What this measurement does and does not establish

The gated arm demonstrates **non-regression**, not the absence of a
relevance cost, and the reason is structural: the benchmark harnesses never
set `capture_origin`, so every LME/LoCoMo/BEAM memory takes the column
default `'unknown'` (`pg_store.py:567`, `pg_schema.py:51`), which is
untrusted. The factor therefore multiplies *every* candidate by the same W,
and a uniform rescale leaves the WRRF order invariant — visibly so in the
LME column, identical to four decimals across W ∈ {1.0, 0.7, 0.6, 0.5}. The
residual movement in LoCoMo (spread 0.0095 R@10, 0.0068 MRR) and BEAM is
non-monotone in W and of the same order as LoCoMo's own same-commit noise
(stdev 0.0022 MRR over 3 reps, `reproduce.sh:339`); this sweep does not
identify its mechanism and should not be read as a W effect.

Consequence: the cost of demotion **under mixed origins** — the production
condition — is not measured by this grid. What is established is that
wiring W = 0.7 cannot regress the published floors, and that 0.7 is the
weakest demotion defending all four attack families. A per-origin relevance
cost would need a corpus whose memories carry mixed `capture_origin` values;
that is a separate measurement, not a gap in this one.

Two provenance notes, stated rather than smoothed over:

- Cells ran at `66d2628f`; the branch head is now `6a52fad6`. The only delta
  is `tests_py/invariants/test_I2_canonical_writer.py` (re-pinned line
  numbers), which no retrieval path imports.
- Every cell logs `consolidation: OFF`, and `reproduce.sh` indeed never
  passes `--with-consolidation` (no occurrence in the script). §Protocol
  above asserted the opposite. Its ≈0% claim holds for a *direct*
  `run_benchmark.py` invocation (CLAUDE.md § Iteration benchmarks) but not
  for `reproduce.sh`, which reproduces the published floors with
  consolidation off — the ≈0% collapse was transposed to the wrong harness.
  §Protocol is left as written, being the pre-registration; this note is the
  correction. What the gate requires still holds: one shared condition
  across all five cells, and a control arm that reproduces the published
  numbers exactly.
