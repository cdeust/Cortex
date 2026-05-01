# Paper Numbers Audit — `docs/arxiv-thermodynamic/main.tex`

**Audited:** 2026-04-30
**Auditor:** data-scientist agent
**Scope:** every numerical benchmark claim in `docs/arxiv-thermodynamic/main.tex`,
cross-referenced against `benchmarks/results/`, `CLAUDE.md`, `docs/papers/thermodynamic-memory-vs-flat-importance.md`, and `docs/arxiv-context-assembly/main.tex`.

## Summary

- **Claims audited:** 14 distinct numerical claims (some appear at multiple line numbers)
- **VERIFIED:** 8
- **MISMATCH:** 1 (BEAM Overall — see C-BEAM below; **hard mismatch**)
- **STALE / WITHIN TOLERANCE:** 4 (post-refactor benchmarks deviate by ≤0.5pp from cited values; all PASS the project's own ≤0.5pp design-doc tolerance, but cited number predates the refactor)
- **UNVERIFIABLE:** 1 (LongMemEval paper-best 78.4% — external citation, not a Cortex result)
- **SMOKE-TEST FLAGGED:** 0 numbers from smoke-test artifacts found in this paper
- **NOT FOUND in this paper:** the 27pp decay-sweep claim and the BEAM-10M 0.471 / 0.353 / +33.4% claims (those live in `docs/arxiv-context-assembly/main.tex`, not in arxiv-thermodynamic). Verified separately for cross-paper consistency.

## Audit Table

| # | Claim | Paper line(s) | Source (file:line) | Source value | Status | Notes |
|---|---|---|---|---|---|---|
| 1 | LongMemEval R@10 = 97.8% | main.tex:50, 88, 447, 821, 1040, 1099, 1259 | `CLAUDE.md:344`; `benchmarks/results/phase5_longmemeval_post_refactor.md:13`; `a3_longmemeval_post_refactor.md:13` | 97.8% | VERIFIED | Exact match across CLAUDE.md, A3, phase5 post-refactor. |
| 2 | LongMemEval MRR = 0.882 | main.tex:448 | `CLAUDE.md:345` (0.882); `phase5_longmemeval_post_refactor.md:14` (0.881); `a3_longmemeval_post_refactor.md:14` (0.881) | 0.882 (CLAUDE.md), 0.881 (post-refactor) | VERIFIED (within tolerance) | CLAUDE.md authoritative table says 0.882. Post-refactor measured 0.881 — within design-doc 0.5pp tolerance, marked PASS by project's own gate. |
| 3 | LoCoMo R@10 = 92.6% | main.tex:51, 449, 1259 | `CLAUDE.md:346` (92.6%); `a3_locomo_post_refactor.md:13` (92.3%); `phase5_longmemeval_post_refactor.md:74` (92.3%) | 92.6% in CLAUDE.md; 92.3% in post-refactor | VERIFIED (within tolerance) | -0.3pp drift from refactor; project gate says PASS (<0.5pp). Paper cites pre-refactor authoritative number. |
| 4 | LoCoMo MRR = 0.794 | main.tex:450 | `CLAUDE.md:347` (0.794); `a3_locomo_post_refactor.md:14` (0.791); `phase5_longmemeval_post_refactor.md:75` (0.791) | 0.794 in CLAUDE.md; 0.791 in post-refactor | VERIFIED (within tolerance) | Same situation as LoCoMo R@10. -0.003 absolute, within 0.5pp tolerance. |
| 5 | **BEAM Overall = 0.543** | main.tex:51, 90, 451, 1259 | `CLAUDE.md:348` (0.543); `a3_beam_100k_post_refactor.md:36` (Overall MRR **0.591**); `a3_beam_100k_post_refactor.md:29` (`information_extraction` MRR **0.543**) | **OVERALL is 0.591, not 0.543**. 0.543 is the `information_extraction` sub-ability, not Overall. | **MISMATCH (hard)** | The CLAUDE.md table also has 0.543 — both that table and the paper appear to have copied a sub-metric into the Overall slot. The actual A3 BEAM-100K Overall MRR is **0.591** (matched exactly to README v3.11 baseline, exact pass). The paper's headline "+65% relative gain on BEAM Overall" (line 456) recomputes to **+79.6%** with the correct 0.591 figure (still favorable). This is a **hard mismatch** that must be corrected. |
| 6 | BEAM paper-best Overall = 0.329 | main.tex:90, 451 | `a3_beam_100k_post_refactor.md:36` (Paper LIGHT OVERALL 0.329) | 0.329 | VERIFIED | LIGHT (Llama-4-Maverick) overall on BEAM-100K matches. |
| 7 | LongMemEval paper-best R@10 = 78.4% | main.tex:50, 89, 447, 822, 837, 1037, 1099 | External citation \citep{Wu2025} | (paper figure, not Cortex-measured) | UNVERIFIABLE LOCALLY | Standard practice for citing external benchmark; not a defect, but flagged so reviewer knows it depends on Wu et al. 2025 reporting. |
| 8 | +19.4 pp absolute LongMemEval gain | main.tex:456, 823, 839, 881, 1040 | Derived: 97.8 − 78.4 = 19.4 | 19.4 pp | VERIFIED | Arithmetic correct given claims 1 and 7. |
| 9 | +65% relative BEAM Overall gain | main.tex:456 | Derived: (0.543 − 0.329)/0.329 = 65.0% | 65.0% with 0.543; **79.6% with the correct 0.591** | **MISMATCH (consequence of #5)** | If 0.543 is corrected to 0.591, this number becomes +79.6%. Either way, the qualitative claim ("largest relative gain") survives, but the magnitude is wrong. |
| 10 | λ_base = 0.95 (decay) | main.tex:240, 497 | `mcp_server/core/thermodynamics.py` (per CLAUDE.md L497-498 self-citation); `decay_sweep/.../analysis.json` shows optimum_lambda=0.95 | 0.95 | VERIFIED | Constant matches both code and the decay-sweep optimum. |
| 11 | λ_important = 0.998 | main.tex:498 | Self-cited code constant in thermodynamics.py | 0.998 | UNVERIFIABLE FROM BENCH DATA | No benchmark artifact pins this; it is an engineering choice, properly disclosed as such in §Limitations (line 497-505). |
| 12 | r = 0.5 (emotional resistance) | main.tex:498 | Self-cited code constant | 0.5 | UNVERIFIABLE FROM BENCH DATA | Same — engineering choice, disclosed. |
| 13 | LongMemEval-S N≈10⁴ corpus, 500 questions | main.tex:826, 1032 | LongMemEval paper (Wu 2025) standard parameters | 500 questions standard | VERIFIED | Matches public benchmark spec. |
| 14 | C5 generalization claim: LoCoMo R@10 ≥ 0.88 | main.tex:1204 | `CLAUDE.md:346` (92.6%) → 0.926 ≥ 0.88 | satisfied | VERIFIED | Predicted threshold met. |

## Cross-paper consistency check (`docs/arxiv-context-assembly/main.tex`, prior paper)

The user requested verification of BEAM-10M numbers cited in the prior paper:

| Claim | Prior-paper line | Source | Source value | Status |
|---|---|---|---|---|
| BEAM-10M MRR 0.471 (assembler) | `docs/arxiv-context-assembly/main.tex:46, 1448, 1684, 1691, 2295` | `a3_locomo_post_refactor.md:49` (README floor ≥0.471); `a3_beam_100k_post_refactor.md:68` (README floor 0.471) | 0.471 floor | VERIFIED (consistent with floor) — note: this is the floor, not a freshly-measured number; prior paper treats it as the headline assembler result. |
| BEAM-10M flat MRR 0.353 | `docs/arxiv-context-assembly/main.tex:35, 148, 1448` | `docs/arxiv-context-assembly/main.tex` self-reports | 0.353 | UNVERIFIABLE LOCALLY (no `benchmarks/results/beam_10m/...` artifact present in this audit's scope; prior paper's measurement) |
| +33.4% improvement | `docs/arxiv-context-assembly/main.tex:46, 225, 1448, 2004` | Derived: (0.471−0.353)/0.353 = 33.4% | 33.4% | VERIFIED (arithmetic) given the two source values. |

## 27pp decay-sweep claim

The user listed "Decay sweep λ=0.95 vs λ=1.0 = 27pp gap" as a high-priority claim to verify. **This claim does not appear in `docs/arxiv-thermodynamic/main.tex`.** A grep for "27" + "pp/gap/sweep" returns no hits. The decay sweep artifact (`benchmarks/results/decay_sweep/20260430T111134Z/summary.csv`) shows:

- λ=0.95: MRR 0.671, R@5 0.833, R@10 0.867
- λ=1.00: MRR 0.399, R@5 0.483, R@10 0.567
- Δ MRR: +0.272 (≈ 27.2pp on the MRR axis if expressed in points), Δ R@10: +30.0pp

**If "27pp" was intended to refer to the MRR delta of 0.272**, it is approximately verified (27.2pp). **If it was intended to refer to R@10 delta**, the correct figure is 30.0pp. The decay sweep is a 2-point sweep on a small N with `quick=true` flag → this is a **smoke-test-grade artifact** and should be flagged as such if cited as evidence. It is currently NOT cited in the paper, so no action needed in arxiv-thermodynamic; but if added later, **must be labeled as smoke-test / 2-point sweep, not a production number**.

## Recommended actions (ordered by severity)

1. **HARD FIX (must correct before submission):** main.tex:51, 90, 451, 1259 — change BEAM Overall **0.543 → 0.591** to match the actual A3 BEAM-100K Overall MRR. CLAUDE.md:348 must also be updated. Update derived "+65% relative gain" (line 456) to **+79.6%**.

2. **SOFT FIX (optional but recommended):** Update LongMemEval MRR (0.882→0.881), LoCoMo R@10 (92.6%→92.3%), LoCoMo MRR (0.794→0.791) to the post-refactor measured values, OR add a footnote that headline numbers are pre-A3-refactor and that post-refactor values fall within 0.5pp tolerance. The current values pass the project's own design-doc gate, so this is a presentation choice rather than a defect — but reviewer-facing transparency favors disclosure.

3. **NO ACTION NEEDED:** decay constants (λ_base, λ_important, r) — already disclosed as engineering choices in §Limitations. External paper-best citations (78.4%) — standard practice.

4. **CONSIDER:** The paper's "Caveat (iii)" (line 486) says "BEAM's Overall is a composite of seven sub-metrics — see `benchmarks/beam/` for the per-subset breakdown." The actual breakdown has **ten abilities** in the A3 report, not seven. Either reconcile the count or update the caveat.

---

**Audit verdict: FAIL with 1 hard mismatch that must be corrected before submission.**

(The BEAM Overall 0.543→0.591 substitution is a single localized fix but it is reproduced at four line numbers in the paper and once in CLAUDE.md, and it propagates into the +65%→+79.6% derived headline. All other claims are VERIFIED, within-tolerance, or properly-disclosed external citations.)
