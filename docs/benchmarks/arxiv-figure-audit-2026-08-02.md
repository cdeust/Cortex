# arXiv benchmark-figure audit — 2026-08-02

This audit records the pre-submission check requested in issue #347. It covers the benchmark figures in `docs/arxiv-thermodynamic/main.tex`, `docs/arxiv-context-assembly/main.tex`, and their Markdown source documents.

## Authoritative run records

| Benchmark | Current figure | Run record | Code / protocol |
|---|---:|---|---|
| LongMemEval-S, current headline | MRR 0.9167, R@10 0.982, n=500 | `benchmarks/results/repro/20260714-v4.14.1-pretag/longmemeval-s.json` | code SHA `28145f0b7a113fc06e22568de6feea7f8444eaf5`, dirty=false, 2026-07-14 |
| LongMemEval-S, E1 v3 ablation snapshot | MRR 0.9124, R@10 0.984, n=500 | `docs/benchmarks/e1-v3-results.md`; `benchmarks/results/ablation/longmemeval-s_v3/` | code SHA `0e858e8db0f8a5dae0879fa0134113d101be19f8`, dirty=false, 2026-05-03; historical protocol-specific decomposition, not the current headline |
| LoCoMo | MRR 0.8278, R@10 0.942, n=1986 | `docs/benchmarks/e1-v3-locomo-results.md`; `benchmarks/results/ablation/locomo_v3/` (committed, verified present) | code SHA `ef178da7418a05bcf7aeb3e66f5b3179fdad2c4d`, dirty=false, 2026-05-03 — **before** the plasticity fix `5f737fe`, not after (correction, review round 2: see note below) |
| BEAM-100K, flat WRRF | retrieval-proxy MRR 0.591, R@10 0.790, n=100 | `benchmarks/results/a3_beam_100k_post_refactor.md` and `benchmarks/beam/variance/baseline_limit5.txt` | code SHA `a071d89`, five-conversation A/B protocol; result committed by `544abe7` |
| BEAM-100K, assembler | MRR 0.602, n=100 | `benchmarks/beam/variance/assembler_limit5.txt` | same five-conversation A/B protocol |
| BEAM-10M, flat / oracle / temporal | MRR 0.353 / 0.429 / 0.471, n=196 | `benchmarks/beam/variance/baseline_10m_fixed.txt`, `assembler_10m_stagefixed.txt`, `assembler_10m_temporal.txt` | original paired protocol |
| BEAM-10M reproduction, oracle / temporal | MRR 0.496 / 0.523, n=196 | `benchmarks/results/beam10m_paired/RESULTS.md` | later paired code revision; compare within this pair only |
| BEAM-500K / 1M crossover | flat 0.500 / 0.466; assembler 0.570 / 0.535 | `benchmarks/results/beam_crossover/RESULTS.md` | clean DB, 35 conversations per split |

## Per-category provenance (added 2026-08-10, PR review follow-up on #347)

**Correction (review round 2):** an earlier version of this section
asserted the `benchmarks/results/ablation/longmemeval-s_v3/BASELINE.json`
run had no code SHA (`manifest.repro = null`). That is true of the field
*embedded in that JSON file* (an older per-row schema that predates the
`manifest.repro` convention), but the **sibling** `benchmarks/results/ablation/longmemeval-s_v3/manifest.json`
does carry one: `code_hash: 0e858e8db0f8a5dae0879fa0134113d101be19f8`,
`dirty: false`, `started_at: 2026-05-02T22:39:22Z`. The run is real,
dateable, and commit-anchored — the earlier claim was wrong, and the
conclusion it supported ("provenance defect, not a regression") does not
follow from it. Corrected below.

The current committed LongMemEval-S run (`28145f0b`, `Temporal reasoning`
MRR 0.917/R@10 97.7%, `Single-session (preference)` MRR 0.685/R@10 90.0%)
is lower on two of six categories than the BASELINE row at `0e858e8`
(2026-05-02/03; MRR 0.9256/R@10 98.5% and MRR 0.6678/R@10 93.3%
respectively). A lower published figure is a regression only if the SAME
protocol produced the higher number before a code change and the lower
number after it — the test is whether a commit boundary between the two
runs contains the drop, not whether the low value has since been stable.

Checked against every committed, git-SHA-tracked run of the same
`--variant s`, `with_consolidation=false` harness:

| Date | Run | Temporal reasoning R@10 | Single-session (pref) R@10 |
|---|---|---:|---:|
| 2026-05-02/03 | `benchmarks/results/ablation/longmemeval-s_v3/BASELINE.json`, code SHA `0e858e8`, dirty=false | 98.5% | 93.3% |
| 2026-07-03 | `benchmarks/results/harness_repro/longmemeval_full_20260703.json`, code SHA `1501428524`, dirty=**true** | 97.7% | 90.0% |
| 2026-07-08 → 2026-08-09 | 30 runs, distinct code SHAs, all `benchmarks/results/repro/*/longmemeval-s.json` | 97.7% (every run) | 90.0% (every run) |

**The test for "regression" is satisfied, not just approximated.** A
regression is two measurements of the *same protocol*, at two commits, with
a gap between them. That is exactly what the two endpoints are: both
manifests were opened and compared field by field —

| Field | `0e858e8` (high) | `28145f0b` (low, README's own current run) |
|---|---|---|
| Harness | `--variant s` (17-row driver calls `benchmarks/longmemeval/run_benchmark.py --variant s`) | same script, `n_questions=500` |
| `n` | 500 | 500 |
| `with_consolidation` | `false` | `false` |
| `dirty` | `false` | `false` |
| Date | 2026-05-02 | 2026-07-14 |

Identical protocol, both clean-tree, both git-SHA-anchored. **This is an
established degradation** on two of six LongMemEval-S categories —
`Temporal reasoning` (MRR 0.9256→0.917 down, R@10 98.5%→97.7% down) and
`Single-session (preference)` (R@10 93.3%→90.0% down; MRR moved the other
way, 0.6678→0.685, so this category's regression is on R@10, not MRR) —
not an open question about whether one exists.

**What remains open is which commit caused it**, not whether a regression
exists. The window between the two endpoints (`0e858e8` → `28145f0b`, or
more precisely the first later git-SHA-tracked run at `1501428524`,
2026-07-03) is **269 commits**
(`git log --oneline 0e858e8..1501428524 | wc -l`); no committed artifact
exists inside it. One plausible candidate by commit message alone:
`8a5f31f3 Module #6 — DA active forgetting + decay-path correctness, with
honest falsification (#69)` — touching exactly the mechanism
(`ADAPTIVE_DECAY`) that `docs/benchmarks/e1-v3-per-category.md`'s
pre-existing per-mechanism analysis already names as counterproductive on
`Single-session (preference)`. Closing the window requires re-running
LongMemEval-S at one or more intermediate commits (bisection), which is
benchmark execution out of scope for this PR — the machine is carrying a
separate multi-hour measurement.

**Conclusion and consequence: this is a regression, awaiting a root-cause
commit, not a coin flip between "regression" and "provenance."** A
regression is fixed in code before it is published as a reference value —
the low pair is **not** presented in `README.md` as the current LongMemEval
per-category figure for these two categories; the two rows are withheld
there with a pointer to this section. `docs/benchmarks/e1-v3-per-category.md`
carries both endpoints with the same framing.

## Findings and resolution

- **LongMemEval:** Opus 5's review found that the first audit had incorrectly promoted the May E1 v3 ablation baseline (MRR 0.9124, R@10 98.4%) to the current headline while `README.md` carried 98.2%. The current headline is now the latest committed clean run with an explicit clean flag: MRR 0.9167, R@10 98.2%, n=500, code SHA `28145f0`. The E1 v3 values remain only inside their named historical ablation snapshot and its per-row analysis.
- **LoCoMo (corrected, review round 2):** the previous version of this audit promoted a "post-fix" pair (MRR 0.8279, R@10 94.35%, code SHA `2f45bcb`) that has **no committed per-query artifact anywhere in this repository** — `docs/benchmarks/e1-v3-locomo-results-post-fix.md` cites `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/` as its output directory, and that path does not exist at any commit on any branch (`git log --all --diff-filter=A -- 'benchmarks/results/ablation/locomo_v3_post_plasticity_fix/*'` returns nothing). Publishing that pair while disqualifying the historical 0.794/0.926 comparator for the identical defect (no committed artifact) was inconsistent. The only LoCoMo E1 v3 ablation run with a real, present, committed artifact is `benchmarks/results/ablation/locomo_v3/` — code SHA `ef178da7`, dirty=false, 2026-05-03, `BASELINE_NO_CONSOLIDATION` MRR 0.8278/R@10 94.2% — which is **before**, not after, the plasticity fix `5f737fe`. The thermodynamic paper's headline, benchmark table, 14-row ablation table, contributor narrative, cadence appendix, and both context-assembly citations now use this artifact-backed pair. The "post-fix re-run" narrative in `docs/benchmarks/e1-v3-locomo-results-post-fix.md` is not deleted (it may be correct) but is marked unverified pending a committed re-run; nothing publication-facing cites it as current until then.
- **Historical 0.794 / 0.926 comparator:** this pair is the April 2026 clean-DB Cortex result (n=1982) first published in commit `b4057a`. Its original per-query artefact is not committed. All active citations now label it as a superseded historical comparator rather than attributing it to the current `CLAUDE.md`.
- **BEAM:** the arXiv LaTeX headline already had the correct 0.591 retrieval-proxy MRR from the named five-conversation / 100-question protocol at code SHA `a071d89`. The standalone Popper appendix's stale 0.543 was replaced, and the thermodynamic Markdown source now matches the LaTeX paper by removing the invalid comparison against BEAM's incommensurable end-to-end 0.329 score. The later 395-question full split remains a separate protocol.
- **Publication surfaces:** the thermodynamic and context-assembly LaTeX sources, their Markdown sources, the Popper/Shannon/Erdős appendices, the README benchmark table, and the arXiv endorsement drafts now use the current LongMemEval and LoCoMo headlines. Historical values are retained only with a named run or an explicit historical label.
- **Noise-floor language:** the artifact-backed LoCoMo consolidation-only values (`benchmarks/results/ablation/locomo_v3/`) are all within the stated ±0.002 MRR floor. HOMEOSTATIC_PLASTICITY and SCHEMA_ENGINE end within noise of zero; the papers describe these as positive-direction observations within noise, not causal contributions outside noise — this claim does not depend on the pre-fix/post-fix question above, since both sweeps agreed on it.

## Submission gate

The source-level figure audit passes when:

1. the stale-number grep contains no unlabeled LoCoMo headline (`0.805`, `91.5%`, `94.35%`/`0.8279`/`2f45bcb` — the unbacked pair retracted in review round 2) or current LongMemEval headline (`97.8%`, `98.4%`), and every retained occurrence is explicitly historical, belongs to a named protocol, or represents a different metric;
2. the two LaTeX sources compile without undefined references or citations;
3. `git diff --check` passes.

**Result (superseded twice, most recently by review round 3, 2026-08-10):**
the 2026-08-02 PASS verdict rested on a LoCoMo pair (0.8279/94.35%,
`2f45bcb`) with no committed artifact; review round 2 caught this and the
pair is retracted throughout this repository in favor of the artifact-backed
pre-fix pair (0.8278/94.2%, `ef178da7`, `benchmarks/results/ablation/locomo_v3/`).
Review round 2 also mis-framed the LongMemEval per-category finding as
"cannot be established from committed artifacts alone" — review round 3
corrected this: two committed, clean-tree, same-protocol runs (`0e858e8`
and `28145f0b`) establish a real degradation on `Temporal reasoning` and
`Single-session (preference)`; only the responsible commit (somewhere in
the 269-commit window between them) is unlocalized. `README.md` withholds
those two category rows rather than publishing the low values as reference
figures. PDFs regenerated after the LoCoMo correction; `git diff --check`
passes.
