# arXiv benchmark-figure audit — 2026-08-02

This audit records the pre-submission check requested in issue #347. It covers the benchmark figures in `docs/arxiv-thermodynamic/main.tex`, `docs/arxiv-context-assembly/main.tex`, and their Markdown source documents.

## Authoritative run records

| Benchmark | Current figure | Run record | Code / protocol |
|---|---:|---|---|
| LongMemEval-S | MRR 0.9124, R@10 0.984, n=500 | `docs/benchmarks/e1-v3-results.md` | code SHA `0e858e8db0f8a5dae0879fa0134113d101be19f8`, dirty=false |
| LoCoMo | MRR 0.8279, R@10 0.9435, n=1986 | `docs/benchmarks/e1-v3-locomo-results-post-fix.md` | code SHA `2f45bcb39dbe15fa0ef857cc8c8c3783175d05db`, dirty=false, descendant of `5f737fe` |
| BEAM-100K, flat WRRF | MRR 0.591, n=100 | `benchmarks/results/a3_beam_100k_post_refactor.md` and `benchmarks/beam/variance/baseline_limit5.txt` | five-conversation A/B protocol |
| BEAM-100K, assembler | MRR 0.602, n=100 | `benchmarks/beam/variance/assembler_limit5.txt` | same five-conversation A/B protocol |
| BEAM-10M, flat / oracle / temporal | MRR 0.353 / 0.429 / 0.471, n=196 | `benchmarks/beam/variance/baseline_10m_fixed.txt`, `assembler_10m_stagefixed.txt`, `assembler_10m_temporal.txt` | original paired protocol |
| BEAM-10M reproduction, oracle / temporal | MRR 0.496 / 0.523, n=196 | `benchmarks/results/beam10m_paired/RESULTS.md` | later paired code revision; compare within this pair only |
| BEAM-500K / 1M crossover | flat 0.500 / 0.466; assembler 0.570 / 0.535 | `benchmarks/results/beam_crossover/RESULTS.md` | clean DB, 35 conversations per split |

## Findings and resolution

- **LongMemEval:** the thermodynamic paper already matched the E1 v3 run (MRR 0.9124, R@10 98.4%). The context-assembly Markdown source still cited the older 97.8% figure; it now matches the 98.4% E1 v3 value and its LaTeX mirror.
- **LoCoMo:** the thermodynamic paper's headline, benchmark table, 14-row ablation table, contributor narrative, cadence appendix, and both context-assembly citations still used the pre-fix 0.8278 / 0.942 run. They now use the post-fix 0.8279 / 0.9435 run and its per-row deltas. Pre-fix values remain only in explicitly labelled historical comparisons.
- **Historical 0.794 / 0.926 comparator:** this pair is the April 2026 clean-DB Cortex result (n=1982) first published in commit `b4057a`. Its original per-query artefact is not committed. All active citations now label it as a superseded historical comparator rather than attributing it to the current `CLAUDE.md`.
- **BEAM:** no numerical change was required. The arXiv values match the committed protocol-specific artefacts listed above. The papers continue to distinguish retrieval-proxy MRR from BEAM's end-to-end LLM-as-judge metric and to avoid comparing values across code revisions except within named pairs.
- **Noise-floor language:** the post-fix LoCoMo consolidation-only values are all within the stated ±0.002 MRR floor. HOMEOSTATIC_PLASTICITY and SCHEMA_ENGINE end at +0.0017; the papers now describe these as positive-direction observations within noise, not causal contributions outside noise.

## Submission gate

The source-level figure audit passes when:

1. the stale-number grep contains no unlabeled LoCoMo headline (`0.805`, `91.5%`, `94.2%`) and every retained `0.794 / 0.926` occurrence is explicitly historical or belongs to a different named metric;
2. the two LaTeX sources compile without undefined references or citations;
3. `git diff --check` passes.

**Result: PASS on 2026-08-02.** The stale-number grep has no unlabeled LoCoMo headline; both PDFs were rebuilt with `pdflatex`/`bibtex` and the final passes contain no undefined references or citations; the 14-row LoCoMo values were checked across the post-fix writeup, Markdown paper, and LaTeX source; `scripts/check_doc_claims.py` and `git diff --check` pass.
