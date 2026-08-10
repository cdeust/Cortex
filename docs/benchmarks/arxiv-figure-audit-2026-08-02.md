# arXiv benchmark-figure audit — 2026-08-02

This audit records the pre-submission check requested in issue #347. It covers the benchmark figures in `docs/arxiv-thermodynamic/main.tex`, `docs/arxiv-context-assembly/main.tex`, and their Markdown source documents.

## Authoritative run records

| Benchmark | Current figure | Run record | Code / protocol |
|---|---:|---|---|
| LongMemEval-S, current headline | MRR 0.9167, R@10 0.982, n=500 | `benchmarks/results/repro/20260714-v4.14.1-pretag/longmemeval-s.json` | code SHA `28145f0b7a113fc06e22568de6feea7f8444eaf5`, dirty=false, 2026-07-14 |
| LongMemEval-S, E1 v3 ablation snapshot | MRR 0.9124, R@10 0.984, n=500 | `docs/benchmarks/e1-v3-results.md`; `benchmarks/results/ablation/longmemeval-s_v3/` | code SHA `0e858e8db0f8a5dae0879fa0134113d101be19f8`, dirty=false, 2026-05-03; historical protocol-specific decomposition, not the current headline |
| LoCoMo | MRR 0.8279, R@10 0.9435, n=1986 | `docs/benchmarks/e1-v3-locomo-results-post-fix.md` | code SHA `2f45bcb39dbe15fa0ef857cc8c8c3783175d05db`, dirty=false, descendant of `5f737fe` |
| BEAM-100K, flat WRRF | retrieval-proxy MRR 0.591, R@10 0.790, n=100 | `benchmarks/results/a3_beam_100k_post_refactor.md` and `benchmarks/beam/variance/baseline_limit5.txt` | code SHA `a071d89`, five-conversation A/B protocol; result committed by `544abe7` |
| BEAM-100K, assembler | MRR 0.602, n=100 | `benchmarks/beam/variance/assembler_limit5.txt` | same five-conversation A/B protocol |
| BEAM-10M, flat / oracle / temporal | MRR 0.353 / 0.429 / 0.471, n=196 | `benchmarks/beam/variance/baseline_10m_fixed.txt`, `assembler_10m_stagefixed.txt`, `assembler_10m_temporal.txt` | original paired protocol |
| BEAM-10M reproduction, oracle / temporal | MRR 0.496 / 0.523, n=196 | `benchmarks/results/beam10m_paired/RESULTS.md` | later paired code revision; compare within this pair only |
| BEAM-500K / 1M crossover | flat 0.500 / 0.466; assembler 0.570 / 0.535 | `benchmarks/results/beam_crossover/RESULTS.md` | clean DB, 35 conversations per split |

## Per-category provenance (added 2026-08-10, PR review follow-up on #347)

The README's LongMemEval per-category table (`Temporal reasoning` MRR
0.917/R@10 97.7%, `Single-session (preference)` MRR 0.685/R@10 90.0%) is lower
on two of six categories than `docs/benchmarks/e1-v3-per-category.md`'s
BASELINE row (MRR 0.9256/R@10 98.5% and MRR 0.6678/R@10 93.3% respectively).
A lower published figure is a regression only if the same protocol produced a
higher number before a code change and a lower number after it. Checked
against every committed, git-SHA-tracked `benchmarks/results/repro/*/longmemeval-s.json`
run (`--variant s` harness, `with_consolidation=false` in every case, matching
the BASELINE row's own condition):

| Date range | Runs | Temporal reasoning R@10 | Single-session (pref) R@10 |
|---|---:|---:|---:|
| 2026-07-08 → 2026-08-09 (30 runs, distinct code SHAs) | 30 | 97.7% (every run) | 90.0% (every run) |
| `benchmarks/results/ablation/longmemeval-s_v3/BASELINE.json` (single run, `manifest.repro = null`) | 1 | 98.5% | 93.3% |

The lower pair has been the value at **every** tracked commit for a full
month of active development — there is no commit boundary where it drops
from the higher pair, so there is no fix to root-cause. The higher pair
comes from exactly one run, with no code SHA captured (`manifest.repro`
is `null`), the same defect class as the already-corrected LongMemEval
headline (E1 v3 ablation baseline mis-promoted to current) and the
already-labelled historical LoCoMo 0.794/0.926 comparator. Conclusion:
**provenance defect, not a regression** — the low figures are current and
correct; the high figures are an unreproducible one-off now labelled
historical in `docs/benchmarks/e1-v3-per-category.md`.

## Findings and resolution

- **LongMemEval:** Opus 5's review found that the first audit had incorrectly promoted the May E1 v3 ablation baseline (MRR 0.9124, R@10 98.4%) to the current headline while `README.md` carried 98.2%. The current headline is now the latest committed clean run with an explicit clean flag: MRR 0.9167, R@10 98.2%, n=500, code SHA `28145f0`. The E1 v3 values remain only inside their named historical ablation snapshot and its per-row analysis.
- **LoCoMo:** the thermodynamic paper's headline, benchmark table, 14-row ablation table, contributor narrative, cadence appendix, and both context-assembly citations still used the pre-fix 0.8278 / 0.942 run. They now use the post-fix 0.8279 / 0.9435 run and its per-row deltas. Pre-fix values remain only in explicitly labelled historical comparisons.
- **Historical 0.794 / 0.926 comparator:** this pair is the April 2026 clean-DB Cortex result (n=1982) first published in commit `b4057a`. Its original per-query artefact is not committed. All active citations now label it as a superseded historical comparator rather than attributing it to the current `CLAUDE.md`.
- **BEAM:** the arXiv LaTeX headline already had the correct 0.591 retrieval-proxy MRR from the named five-conversation / 100-question protocol at code SHA `a071d89`. The standalone Popper appendix's stale 0.543 was replaced, and the thermodynamic Markdown source now matches the LaTeX paper by removing the invalid comparison against BEAM's incommensurable end-to-end 0.329 score. The later 395-question full split remains a separate protocol.
- **Publication surfaces:** the thermodynamic and context-assembly LaTeX sources, their Markdown sources, the Popper/Shannon/Erdős appendices, the README benchmark table, and the arXiv endorsement drafts now use the current LongMemEval and LoCoMo headlines. Historical values are retained only with a named run or an explicit historical label.
- **Noise-floor language:** the post-fix LoCoMo consolidation-only values are all within the stated ±0.002 MRR floor. HOMEOSTATIC_PLASTICITY and SCHEMA_ENGINE end at +0.0017; the papers now describe these as positive-direction observations within noise, not causal contributions outside noise.

## Submission gate

The source-level figure audit passes when:

1. the stale-number grep contains no unlabeled LoCoMo headline (`0.805`, `91.5%`, `94.2%`) or current LongMemEval headline (`97.8%`, `98.4%`), and every retained occurrence is explicitly historical, belongs to a named protocol, or represents a different metric;
2. the two LaTeX sources compile without undefined references or citations;
3. `git diff --check` passes.

**Result: PASS after Opus 5 follow-up on 2026-08-02.** The stale-number grep has no unlabeled current LoCoMo or LongMemEval headline; both PDFs were rebuilt with `pdflatex`/`bibtex` and the final passes contain no undefined references or citations; the 14-row LoCoMo values were checked across the post-fix writeup, Markdown paper, and LaTeX source; `scripts/check_doc_claims.py` and `git diff --check` pass.
