# BEAM-10M LLM Head-to-Head Protocol — Pre-Registration (Fisher-style)

**Author:** research-scientist (designed); experiment-runner executes; curie audits before Stage 2.
**Status:** PRE-REGISTERED DRAFT v2 (lightweight-tier rewrite, 2026-04-30) — freezes on commit `<TBD>` (the commit that lands this file plus the harness skeleton at `benchmarks/llm_head_to_head/`).  Changes from v1: generator panel switched from Sonnet 4.6 + Opus 4.7-1M to Haiku 4.5 + GPT-4o mini + Gemini 2.0 Flash; judge mode now cross-vendor; cost drop ~30× on full panel.
**Companions:** `tasks/verification-protocol.md` (Fisher template), `tasks/verification-measurement-discipline.md` (Curie HARD-STOP), `tasks/hnsw-determinism-playbook.md` (DB reproducibility), `docs/papers/thermodynamic-memory-vs-flat-importance.md` (paper under validation), `docs/arxiv/main.tex` (prior BEAM-10M assembler claim: MRR 0.471 vs flat 0.353).
**Critique this protocol closes:** *"You measured retrieval quality without an LLM in the loop, so you can't claim you're better."*  This protocol is the LLM-stage extension that converts retrieval-quality numbers into end-to-end answer accuracy.
**Pre-registration discipline:** OSF-style. After freeze, the analysis is locked. Post-hoc analyses are reported separately as **exploratory**, never relabelled confirmatory.

---

## 0. Glossary of independent variables

- **IV-1 Condition** ∈ {A naive long-context, B standard RAG, C Cortex-assembled, D Oracle}.
- **IV-2 Generator LLM** ∈ {Haiku 4.5 (primary), GPT-4o mini (cross-vendor, full panel), Gemini 2.0 Flash (cross-vendor, full panel)}.  Lightweight tier — see §3 for rationale.
- **Item** = a single BEAM-10M probing question, paired across all (Condition × Generator) cells.
- **Judge LLM** = cross-vendor pairing (Opus 4.7 judges OpenAI + Google generators; GPT-4o judges Anthropic generators).  See §3.

---

## 1. Hypotheses (H1–H3, with explicit null and alternative)

All tests are paired across questions and across LLMs. Significance level α = **0.01** (one-sided where directionally hypothesised; two-sided otherwise).

### H1 — Cortex+LLM beats naive long-context-LLM (the headline)

- **Population.** BEAM-10M questions for which the answer is supported by the chat history (i.e. all non-abstention items: 196 − N_abstention).
- **H1₀ (null):** Accuracy(C, LLM) − Accuracy(A, LLM) ≤ 0 for the median LLM in the panel.
- **H1₁ (alt):** Accuracy(C, LLM) − Accuracy(A, LLM) ≥ **+10 pp** at α = 0.01.
- **Falsification.** C ≤ A + 2 pp on Haiku 4.5 (slim) or panel median (full) → thermodynamic stack confers no end-to-end lift at the production tier.  Paper §6 retrenches to retrieval-only claim.

### H2 — Cortex+LLM beats standard RAG+LLM (the mechanism claim)

- **H2₀ (null):** Accuracy(C, LLM) − Accuracy(B, LLM) ≤ 0.
- **H2₁ (alt):** Accuracy(C, LLM) − Accuracy(B, LLM) ≥ **+5 pp** at α = 0.01.
- **Falsification.** C ≈ B (±2 pp) on Haiku AND ≥1 cross-vendor anchor → thermodynamic features add nothing over dense retrieval at the LLM stage; the lift in `docs/papers/thermodynamic-memory-vs-flat-importance.md` §6 is achievable with vanilla top-k; paper §4 mechanisms unjustified end-to-end.

### H3 — Oracle ceiling vs Cortex (the headroom diagnostic)

- **H3₀ (null):** Accuracy(D, LLM) − Accuracy(C, LLM) ≥ +5 pp.
- **H3₁ (alt):** Accuracy(D, LLM) − Accuracy(C, LLM) < +5 pp.
- **Interpretation.** Null-rejected H3 → Cortex extracts what the LLM needs (paper tightens claims).  Null-not-rejected H3 → real room above Cortex (§7.1 gets a quantitative figure).
- **Falsification of "Cortex is near-ceiling"**: D ≥ C + 10 pp on Haiku 4.5 (slim) or on any panel member (full).

The three tests are pre-registered.  Any further pairwise contrast (e.g. A vs B alone, B vs D) is **exploratory**.

---

## 2. Conditions (the IV-1 manipulation)

The four conditions share an identical answer-generation prompt template (Appendix A, hashed).  They differ ONLY in what is fed to that template.

### A. Naive long-context

- **Build.**  Concatenate the BEAM conversation chat verbatim, in original order, until the token count reaches the generator's context window minus a 4 000-token answer headroom.
- **Truncation rule (load-bearing, anti-cheating §11):** keep the **latest** tokens (recency-truncate from the head).  This matches the standard production approach for "just hand the conversation to the LLM."
- **Per-model context window** (input budget = window − 4 000 output headroom):
  - Haiku 4.5: 196 000 tok; GPT-4o mini: 124 000 tok; Gemini 2.0 Flash: 996 000 tok (1M long-context anchor).
- **Note.**  At ~10 M tokens per BEAM conversation, every model except Gemini-1M *will* truncate — that is what naive long-context produces in practice, not a defect of A.

### B. Standard RAG (top-k vector retrieval, no Cortex stack)

- **Build.**  Embed the question with `sentence-transformers/all-MiniLM-L6-v2` (the same model Cortex uses).  Run top-k cosine over the BEAM memories (k = 20).  Concatenate the retrieved passages.
- **What is *off*.**  No heat, no decay, no consolidation, no neuromodulation, no schema, no synaptic tagging, no WRRF heat term, no FlashRank rerank, no strategic ordering, no co-activation, no triggered-memory injection.  This is the canonical Lewis-2020 RAG.
- **Implementation.**  A separate retrieval helper at `benchmarks/llm_head_to_head/retriever_baselines.py::standard_rag()` that issues the embedding query directly against the same `embedding` column with HNSW cosine — no `recall_memories()`, no PL/pgSQL fusion.
- **k value.**  k = 20 is the published BEAM baseline retrieval depth.  Pre-registered; no sweep.

### C. Cortex-assembled (treatment)

- **Build.**  Call `mcp_server/handlers/recall.py::handler` with `query = question`, `domain = "beam"`, `max_results = 20`.  Concatenate the returned passages.
- **What is *on*.**  All production enrichments: PL/pgSQL WRRF (vector + FTS + trigram + heat + recency + ngram), FlashRank rerank, decay, consolidation cascade, synaptic tagging, neuromodulation, prospective injection, strategic ordering (Liu et al. 2023 mitigation), co-activation Hebbian.
- **Anti-cheating clause.**  This is **the same** call site used in production by every Cortex client.  No `--benchmark-mode` flag, no special path.  Documented at `benchmarks/llm_head_to_head/cortex_caller.py:<line>`.  CI gate: a unit test asserts the call goes through `handlers.recall.handler` with no monkey-patching.

### D. Oracle (ceiling)

- **Build.**  For each question, retrieve the gold-supporting turns directly from the BEAM `source_chat_ids` field (mapping turn-ID → memory content via the same loader the benchmark uses).  Concatenate them with no ranking model in the loop.
- **Interpretation.**  D bounds the best-case answer accuracy *given* the LLM and the prompt template — anything above D is hallucination/confabulation.  D − C measures Cortex's residual retrieval gap.

All four conditions feed their context block into the SAME answer-generation prompt (Appendix A).

---

## 3. LLM panel (IV-2) — lightweight generator tier

### Rationale (rewritten 2026-04-30)

The earlier draft pinned Sonnet 4.6 + Opus 4.7-1M as generators.  This rewrite uses a **lightweight generator panel** for two converging reasons:

1. **The critique this protocol closes is "you didn't run with an LLM in the loop."**  All four conditions feed the SAME generator the SAME prompt; the within-LLM C-vs-A and C-vs-B contrasts are valid at any model tier.
2. **The deployed Cortex serves 1500 users; production cost-per-query bounds favour lightweight generators.**  A win on Haiku / GPT-4o mini / Gemini Flash is the *production-relevant* claim.  Demonstrating the lift on cheap models is therefore a **stronger** product claim, not a weaker one.  Cross-vendor robustness is preserved at the lightweight tier.

### Generator panel (frozen at protocol-freeze)

| Role | Model | Exact version pin | Why included |
|---|---|---|---|
| Generator (primary, in-house) | Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | Anthropic lightweight tier; the model class Cortex would deploy at 1500-user scale. |
| Generator (cross-vendor, OpenAI) | GPT-4o mini | `gpt-4o-mini-2024-07-18` | OpenAI vendor anchor.  Breaks "Anthropic-favouring" alternative explanation. |
| Generator (cross-vendor, Google) | Gemini 2.0 Flash | `gemini-2.0-flash` | Google vendor anchor.  Long-context (1M) at lightweight tier — useful for condition A without Opus prices. |

Each generator is evaluated under all 4 conditions on all 196 items.  **Slim run** = Haiku 4.5 only.  **Full panel** = all three.

Opus 4.7 is **dropped from the generator panel.**  Retained only as a judge.  Re-adding Opus as a robustness generator is a deferred decision (§13, §14).

### Judge panel — cross-vendor to break collusion (Zheng et al. 2023, NeurIPS)

| Generator | Judge | Vendor cross-check |
|---|---|---|
| GPT-4o mini answers | Claude Opus 4.7 (`claude-opus-4-7-20260301`) | Anthropic judges OpenAI ✓ |
| Gemini 2.0 Flash answers | Claude Opus 4.7 (same pin) | Anthropic judges Google ✓ |
| Haiku 4.5 answers | GPT-4o (`gpt-4o-2024-11-20`) | OpenAI judges Anthropic ✓ |

**Single-judge fallback (budget-tight mode).**  If cross-vendor judging is refused at freeze, judge degrades to **Claude Opus 4.7 only**.  In that mode Haiku-judged-by-Opus is in-house — explicitly **flag Haiku results as carrying same-vendor judge bias**, treat GPT-4o-mini and Gemini results as cross-vendor anchors that survive the bias check.  Documented degradation, not silent.

## 4. Scoring rubric

BEAM (Tavakoli et al. 2026, ICLR; arXiv:2510.27246) uses LIGHT — LLM-as-judge with Llama-4-Maverick.  We adopt LIGHT's *protocol* (binary correctness vs gold, abstention as special category) with cross-vendor judges per §3.

### Judge inputs (per item)
`(question, gold_answer, gold_supporting_turns_if_present, candidate_answer, ability_tag)`.

### Judge does NOT see
Condition label A/B/C/D, generator identity, retrieved context block, other conditions' answers for the same question.

### Randomisation
The 4 candidate answers per question are shuffled with `numpy.random.default_rng(seed=20260501 + question_id)`.  Judge emits a 4-way binary verdict; we reverse the permutation to recover per-condition scores.

### Rubric
- **Non-abstention.**  Correct=1 if candidate entails gold (LIGHT criterion: "a reader who knew the gold would consider this factually right"); else 0.  Partial-credit 0.5 follows LIGHT's tie-break for fact-consistent-but-missing-non-essential-detail.
- **Abstention.**  Correct=1 if candidate explicitly declines AND gold is "[NO ANSWER]".  Confident wrong = 0.  Correct decline on answerable item = 0 (over-abstention penalised, BEAM spec).

### Judge prompt
Verbatim in Appendix B; SHA-256 committed at freeze; re-checked before every Stage 2 run.

### Human-validation slice
n=100 stratified items (10 per ability, seed `20260502`).  3 raters score blindly under the same rubric.  **Acceptance:** Cohen's κ (judge vs rater majority) ≥ **0.70** (Landis & Koch 1977).  κ < 0.70 → calibration fails; Stage 2 pauses; revised judge prompt → addendum (no edit to this protocol).

---

## 5. Sample size and minimum detectable effect (MDE)

### Population size
**BEAM-10M total questions = 196** (Tavakoli et al. 2026, Table 2 / `docs/arxiv/main.tex` line 1219: "Each conversation is probed with 20 questions (196 total at 10M due to ...)" ; reproduced in `benchmarks/beam/run_benchmark.py`).  Stratified by 10 abilities (~20 per ability, with abstention skewed lower).

This is the universe.  We do not subsample for the full run — we use all 196 items.  This is unusual luxury vs the task brief's assumption of 6 000 questions; the protocol exploits it.

### MDE for the primary comparison (paired McNemar, α = 0.01, power = 0.80)

McNemar (1947) test for paired binary outcomes uses the **discordant** pairs only.  Let n = 196, p_disc = expected fraction of items where the two conditions disagree.

For BEAM-10M with the assembler's published lift (0.471 vs 0.353 MRR; ~+12 pp at the answer-relevant top-1 level), we expect p_disc ≈ 0.25–0.35 on H1.  Conservative case p_disc = 0.20 → expected discordant n_d = 39.

McNemar power formula (Connor 1987, *Sample size for testing differences in proportions for the paired-sample design*, Biometrics 43:207–211):
- For α = 0.01 (two-sided), power 0.80, n_d = 39 → **MDE on the proportion difference ≈ 13 pp** (signed).
- For p_disc = 0.30 → n_d = 59 → **MDE ≈ 11 pp**.
- For p_disc = 0.40 → n_d = 78 → **MDE ≈ 9.5 pp**.

**Pre-registered MDE for H1 = 10 pp.**  This sits just above the median-case detectability at α = 0.01 / power 0.80, which is appropriate for a high-stakes claim.

### MDE for H2 (paired McNemar, α = 0.01, power = 0.80)
H2 expects +5 pp.  At p_disc = 0.20, the slim-run (n=196) detectable shift is 13 pp — **underpowered at α = 0.01** with single-LLM data.  **Mitigation:** H2 uses panel-pooled paired bootstrap treating each (question × generator) pair as an observation.  Full panel (n=588) → MDE ≈ 6 pp at α = 0.01, adequate.  Slim-run H2 will likely report as "directional but not significant"; full-panel H2 is the powered comparison.

### MDE for H3 (one-sided, paired McNemar, α = 0.01, power = 0.80)
At n = 196 the detectable headroom is ≈ 11 pp.  Adequate for the falsification rule (D ≥ C + 10 pp).

### Sample-size calculation provenance
- McNemar (1947), *Note on the sampling error of the difference between correlated proportions or percentages*, Psychometrika 12:153–157.
- Connor (1987) for discordant-pair power.
- We do NOT cite the Park & Lee 2018 normal approximation because it overstates power at small p_disc.

### Stratified random sampling (slim version only)
If the slim version (§13) is run instead of the full, the sample is **all 196 items** (slim is not a sub-sample by item — it is a sub-sample by LLM × condition).  The "1500 questions" mentioned in the task brief does not apply to BEAM-10M, which only has 196.

---

### Power discussion at the lightweight tier (added 2026-04-30)

Smaller generators have higher answer-quality variance than frontier models, with two opposing effects on McNemar power:

- **p_disc may rise** (more disagreement between conditions per item) — *increases* power.  Estimate: lightweight-tier p_disc ≈ 0.30–0.45 vs v1's Sonnet-tier 0.25–0.35.
- **Accuracy ceiling drops** (model less able to use retrieved context) — *shrinks* dynamic range.  If Haiku's BEAM-10M ceiling is 0.55 rather than 0.75, the maximum observable C−A delta is bounded accordingly.

Net effect on MDE is uncertain a priori.  We pre-register the same MDE thresholds as v1 and **mark them as estimates to refine in the pilot**.  The pilot's first job is to measure p_disc on Haiku 4.5 directly (B vs C, all 196 items); if p_disc < 0.20, H1 power < 0.80 at α=0.01 and we enter an addendum decision: (i) accept lower power + wider CIs, (ii) escalate to full panel for n=588 panel-pooled, (iii) defer Stage 2.  This is honest reporting — the user's 1500-user product runs on the lightweight tier, so lightweight-tier power is the production-relevant power.

## 6. Statistical tests (pre-registered)

### Primary tests (one per hypothesis)
1. **H1 — McNemar exact (one-sided).**  Per generator, paired binary correctness on the same 196 items, conditions C vs A.  Reject H1₀ if McNemar p < 0.01 AND the observed effect ≥ 10 pp.
2. **H2 — McNemar exact (one-sided).**  Per generator, conditions C vs B.  Reject H2₀ if p < 0.01 AND effect ≥ 5 pp.  Panel-pooled paired bootstrap (10 000 resamples, seed 20260503) reports the 99% CI on the effect across the panel.
3. **H3 — McNemar exact (one-sided).**  Per generator, conditions D vs C.  Reject "Cortex near-ceiling" if D − C ≥ 10 pp at p < 0.01; reject H3₀ ("there is room above Cortex") if D − C < 5 pp at p < 0.01 from the *upper* bound of the bootstrap CI.

### Multiple-comparison correction
3 hypotheses × up to 3 generators = 9 confirmatory tests.  This protocol tests only the 3 pre-registered pairs (C-A, C-B, D-C); other pairwise contrasts are exploratory.  Apply **Holm–Bonferroni** (Holm 1979) at family-wise α = 0.01 within the per-generator family.  Cross-LLM replication is descriptive, not corrected.

### Secondary (descriptive)
- Per-ability accuracy table (10 BEAM abilities × 4 conditions × generators).  No tests, just CIs.
- Effect-size: log-odds ratio with 99% bootstrap CI per pair.
- Calibration: Brier score per condition (when the generator emits a probability via prompt template variant; exploratory).

### Paired bootstrap (Efron 1979)
- Efron, B. (1979), *Bootstrap methods: another look at the jackknife*, Annals of Statistics 7(1):1–26.
- 10 000 resamples, seed pinned at `numpy.random.default_rng(seed=20260503)`.
- Used for: panel-pooled H2 effect; per-condition accuracy CIs; H3 upper-bound check.

---

## 7. Cost estimate (USD) — recomputed for lightweight tier (2026-04-30)

### Verified pricing (snapshotted at protocol-freeze; record SHA in manifest)

| Model | Input ($/M tok) | Output ($/M tok) | Source (verified 2026-04-30) |
|---|---|---|---|
| Claude Haiku 4.5 | **$1.00** | **$5.00** | Anthropic API pricing (`platform.claude.com/docs/en/about-claude/pricing`) |
| GPT-4o mini | **$0.15** | **$0.60** | OpenAI API pricing (`developers.openai.com/api/docs/pricing`) |
| Gemini 2.0 Flash | **$0.10** (text) | **$0.40** | Google AI pricing (`ai.google.dev/pricing`, paid Tier 1).  **Deprecation 2026-06-01:** if Stage 2 fires after that date, switch to Gemini 2.5 Flash and re-snapshot in addendum. |
| Claude Opus 4.7 (judge) | **$5.00** | **$25.00** | Anthropic API pricing (1M context now standard pricing — no premium tier). |
| GPT-4o (cross-vendor judge for Haiku) | **$2.50** | **$10.00** | OpenAI API pricing. |

The user's request mentioned $0.80/$4 (Haiku) and $0.075/$0.30 (Gemini Flash); current rate cards show $1/$5 and $0.10/$0.40.  We use the **verified rate-card values** — Move 5 reproducibility constraint, sources over claims.

### Per-item input-token estimate

- A (naive long-context): Haiku 196 000 / GPT-4o-mini 124 000 / Gemini Flash 996 000 (model-context-window minus 4 000 output headroom).
- B (standard RAG, k=20): ~4 500 input tok.
- C (Cortex top-20): ~4 500 input tok.
- D (oracle): ~1 500 input tok.

Output: ~150 tokens/answer (will measure 99th percentile in pilot).  Judge per-item: ~5 500 input + ~100 output.

### Slim run — Haiku 4.5 only, all 4 conditions, all 196 items, judged by GPT-4o

- Generator: A 38.4M × $1 + 0.029M × $5 = $38.55; B = C = $1.03; D = $0.44.  **Generator subtotal $41.**
- Judge: 5 500 × 196 = 1.08 M × $2.50 + 0.020 M × $10 = **$2.90**.
- **Slim total ≈ $44.**  With 30% buffer (retries, output variance, pricing drift): **slim 95% CI = $40 – $60**.

### Full-panel run — Haiku 4.5 + GPT-4o mini + Gemini 2.0 Flash, all 4 conditions, all 196 items

| Generator | A | B | C | D | Subtotal |
|---|---|---|---|---|---|
| Haiku 4.5 | $38.55 | $1.03 | $1.03 | $0.44 | **$41.05** |
| GPT-4o mini | $3.66 | $0.15 | $0.15 | $0.06 | **$4.02** |
| Gemini 2.0 Flash | $19.53 | $0.10 | $0.10 | $0.04 | **$19.77** |
| **Generator total** | | | | | **$64.84** |

Judge (cross-vendor mode, 588 judge calls = 196 × 3 generators):
- Opus 4.7 judges GPT-4o-mini answers: $5.90; Opus judges Gemini answers: $5.90; GPT-4o judges Haiku answers: $2.90.  **Judge subtotal $14.70**.
- Single-judge fallback (Opus only on all 588): **$17.70**.

**Full-panel total ≈ $80** (cross-vendor) / **$83** (single-judge).  With 30% buffer: **full-panel 95% CI = $65 – $130**.

### Cost reduction vs prior draft

This is a **~30× reduction** vs the v1 Sonnet+Opus-1M draft ($2 800–$5 200 full).  The savings come from (1) dropping Opus-1M as a generator (which alone was $2 928 in input tokens for condition A), and (2) Haiku replacing Sonnet at 1/3 the input rate.  Slim is **3×** cheaper than v1's slim.

### API call count

- **Slim:** 196 × 4 = 784 generator calls + 196 judge calls = **980 distinct API calls** (~1 030 with retries).
- **Full panel:** 3 × 196 × 4 = 2 352 generator + 588 judge = **2 940 distinct API calls** (~3 090 with retries).  Same count under either judging mode.

## 8. Pilot study (Stage 1)

Before the full run:
- **Items.**  200 items.  Wait — BEAM-10M has only 196 total.  Resolution: pilot = **all 196 items, single LLM (Haiku 4.5), conditions B + C only (skip A and D in pilot)**.  This is the cheapest stress-test of the harness.
- **Budget cap.**  $50.  If exceeded by 50%, stop and re-estimate.
- **Goals.**
  1. Confirm LLM-judge κ ≥ 0.70 vs human raters on the 100-item slice (§4).
  2. Calibrate token budget (output token mean and 99th percentile per condition).
  3. Detect prompt-template leakage (e.g. condition label bleeding into the answer).
  4. Sanity-check the harness: end-to-end latency, error rates, retry storms.

### Go/no-go to Stage 2
**GO** if all of:
1. Judge κ ≥ 0.70 with humans.
2. End-to-end success rate ≥ 95% (no API errors, no parse failures).
3. C beats B on Haiku 4.5 by **at least +3 pp** raw (no significance test required at this stage; this is a "is the signal even directionally there" gate).
4. Total pilot cost within ±50% of estimate.

**NO-GO** if any of those fail.  Triggers an addendum file (`tasks/beam-10m-llm-h2h-addendum-001.md`) with diagnosis + revised estimates.  This protocol does NOT auto-edit on no-go.

---

## 9. Failure modes (Popper-severity per hypothesis)

| H | Falsifying observation | Implication |
|---|---|---|
| H1 | C ≤ A + 2 pp on Haiku 4.5 (slim) AND on at least one cross-vendor anchor (full) | Thermodynamic stack confers no LLM-stage lift over naive long-context.  Paper §6 retrenches to retrieval-only claim. |
| H2 | C ≤ B + 2 pp on Haiku 4.5 (panel-pooled bootstrap 99% CI includes 0 at the lightweight tier) | §4 mechanisms (decay, neuromodulation, schema) add nothing on top of dense top-k.  Ablation §3 priorities flipped. |
| H3 | D − C ≥ 10 pp at α = 0.01 | Real headroom above Cortex.  Quantifies §7.1 limitation.  Drives next-quarter retrieval research. |
| H3 (other side) | D − C < 5 pp at p < 0.01 | Cortex is near-ceiling — strongest possible H3 outcome; informs §6 paragraph "where the gap is smaller." |

Anti-fragile note (Popper 1959, *The Logic of Scientific Discovery*): the protocol pre-commits to publishing **all three falsification rulings**, not just the favourable ones.  A negative-result entry per hypothesis is mandatory in `tasks/negative-results-log.md`.

---

### Pre-registered alternative outcomes (out of current scope, flagged for follow-up)

The lightweight-tier rewrite raises two alternatives **explicitly out of pre-registration**, recorded so post-hoc observation is not silently rebranded confirmatory:

- **Alt-1.  Lightweight tier shows H1 lift, Opus tier would show none.**  Cortex primarily helps weak models close the gap to frontier long-context.  Product story: Cortex makes cheap tier viable for use cases that would otherwise require frontier.  Follow-up paper; testing requires +$2 800–$5 200 Opus run.
- **Alt-2.  Lightweight null, Opus would have lifted.**  Cortex rewards stronger reasoning; small models cannot fully exploit assembled context.  Without an Opus run a lightweight null is ambiguous between "Cortex doesn't work" and "Haiku can't use it" — see §13/§14 deferred decision.

§9 falsification rules apply under the lightweight-tier framing only.  A lightweight null does not falsify Cortex-on-Opus; a lightweight positive does not warrant Opus generalisation claims.

## 10. Reproducibility manifest (mandatory, per §verification-protocol §global invariants and §hnsw-determinism-playbook §5)

Every scored run emits a `manifest.json` in `benchmarks/llm_head_to_head/results/<runid>/` with:

```yaml
# Code & data: code_hash, beam_dataset_sha, embedding_cache_sha, package_lockfile_sha (uv.lock)
# DB (HNSW playbook §5): pgvector_extversion, pg_server_version_num,
#   hnsw_index_params {m:16, ef_construction:64, ef_search:40, vector_cosine_ops}, db_snapshot_sha
# LLMs (frozen at Stage 2 start)
generator_models:
  haiku_4_5:  {api: anthropic, model_id: claude-haiku-4-5-20251001}   # slim + full
  gpt4o_mini: {api: openai,    model_id: gpt-4o-mini-2024-07-18}      # full panel
  gemini_2_0: {api: google,    model_id: gemini-2.0-flash}             # full panel
judge_models:
  opus_4_7: {api: anthropic, model_id: claude-opus-4-7-20260301}      # judges OpenAI+Google
  gpt4o:    {api: openai,    model_id: gpt-4o-2024-11-20}             # judges Anthropic
judge_mode: <cross_vendor | single_judge_opus>
pricing_snapshot_sha: <SHA of freeze-time pricing-page captures>
# Prompts: answer_prompt_sha, judge_prompt_sha, shuffle_seed_base: 20260501
# Stats: bootstrap_seed: 20260503; holm_bonferroni_family_alpha: 0.01
# Hardware: hostname, uname -a, RAM, CPU, wall_clock_start/end, api_call_log_sha, stopping_reason
```

Missing field → run downgraded to **exploratory** per `verification-protocol.md` global invariants.

---

## 11. Anti-cheating clauses (the user's critique to defeat)

1. **Same recall path as production.**  Condition C goes through `mcp_server/handlers/recall.py::handler`.  CI gate: unit test asserts the production call site, no monkey-patch, no `--benchmark-mode`.
2. **Honest naive truncation.**  Condition A truncates from the head (keeps latest tokens).  Deviation requires pre-Stage-2 addendum.
3. **Blind judging.**  Judge sees only `(question, gold, ability_tag, candidate)` with answers shuffled; prompt forbids source-guessing.
4. **Pre-registered prompts.**  Appendices A & B SHA-256-hashed at freeze.  Post-freeze change → addendum + re-run.
5. **No seed cherry-picking.**  Seeds `20260501/02/03` fixed at freeze.  Different seeds = exploratory.
6. **No best-of-N.**  One generation per (item × condition × generator).  Temperature = 0 (or vendor floor).  That one result is the result.
7. **Negative log mandatory.**  Every failed test → `tasks/negative-results-log.md` with manifest pointer, never silently re-run.

---

## 12. Timeline & responsibilities

| Day | Owner | Action |
|---|---|---|
| 0 | research-scientist (this file) + engineer | Freeze protocol commit; engineer commits skeleton at `benchmarks/llm_head_to_head/`. |
| 0 | engineer | Build the harness: 4 condition runners, 1 judge runner, manifest emitter, retry/back-off, deterministic shuffling.  Unit-test the production-handler invariant (anti-cheating §11.1). |
| 0–2 | engineer | Verify BEAM-10M DB snapshot reproducibility per HNSW playbook §7-Q7. |
| 2 | experiment-runner | Smoke test: 5 items × condition C × Haiku 4.5 → manifest sanity-check. |
| 3–5 | experiment-runner | Stage 1 pilot (Haiku 4.5 × {B, C} × 196 items + GPT-4o judge).  Cost ≤ $20.  Report to research-scientist + curie. |
| 5 | research-scientist + curie | Audit pilot: judge κ, calibration, signal direction.  Go/no-go decision per §8. |
| 6–8 | experiment-runner | Stage 2 slim run (Haiku 4.5 × all 4 conditions × 196 items + GPT-4o judge).  Cost ≤ $80. |
| 8 | research-scientist | Lock the slim numbers; write up Stage-2-slim results.  Decide whether to commit budget for full run. |
| 9–11 | experiment-runner | Stage 2 full panel (add GPT-4o mini + Gemini 2.0 Flash).  Cost ≤ $150 upper bound (cross-vendor judging).  Auto-Mode budget release at this magnitude is acceptable without an extra OK; only the optional Opus-1M robustness study (§13) requires explicit budget approval. |
| 12 | curie | Final audit against `tasks/verification-measurement-discipline.md` HARD-STOP checklist.  Any failure → Stage 2 results downgraded to exploratory. |
| 13 | research-scientist + paper-writer | Write up; H1/H2/H3 verdicts; negative-results-log entries; commit. |

---

## 13. Cost-control levers — slim vs full panel (rewritten 2026-04-30)

| Variant | Generators | Conditions | Items | Approx cost (USD, 95% CI) | What you can claim |
|---|---|---|---|---|---|
| **Smoke** | Haiku 4.5 | C only | 5 | <$1 | Harness works. |
| **Pilot** (Stage 1) | Haiku 4.5 | B, C | 196 | $5–$10 + κ-validation | Judge calibration; signal direction; p_disc estimate. |
| **Slim** (Stage 2 slim) | Haiku 4.5 | A, B, C, D | 196 | **$40 – $60** | H1, H2, H3 *on Haiku only*.  No vendor-bias control.  H2 likely directional, not significant at α=0.01 alone. |
| **Full panel** (Stage 2 full) | Haiku 4.5 + GPT-4o mini + Gemini 2.0 Flash | A, B, C, D | 196 | **$65 – $130** | All three Hs on the lightweight panel; vendor-bias control; H2 powered via panel-pooling (n=588); production-relevant claim. |
| **Optional Opus robustness add-on** | + Opus 4.7-1M | A, B, C, D | 196 | +$2 800 – $5 200 | Disambiguates Alt-1 vs Alt-2 (§9).  Not currently funded.  User decision. |

### "Minimum to publish" — research-scientist decision

The **slim version** (≈$50) is the minimum to honestly close the user's critique with rigorous numbers.  The **full panel** (≈$100) is the **recommended primary deliverable** — it costs roughly what the v1 slim cost ($141) and answers strictly more questions: vendor-bias control, H2 panel-pooled significance, production-tier robustness.  Given the cost reduction, full panel is now the affordable default rather than a stretch goal.

### Why the lightweight tier is the stronger product claim

User's 1500-user product runs on the lightweight class.  *"Cortex lifts the model class we actually deploy"* is stronger than *"Cortex lifts a class we cannot afford to ship."*  Counter-arguments closed: (i) "you only beat naive context because the model couldn't fit it" — refuted by Gemini Flash 1M in condition A; (ii) "vendor bias" — refuted by 3 cross-vendor generators + cross-vendor judges; (iii) "frontier would close the gap on its own" — out of scope, preserved as Alt-1/Alt-2 follow-up (§9).

## 14. Deferred decisions that need user judgment before Stage 1 fires (rewritten 2026-04-30)

1. **Cross-vendor judging vs single-judge fallback.**  Cross-vendor judging adds ~$3 to slim and ~$5 to full panel — negligible.  Default: cross-vendor.  User to confirm or downgrade.
2. **Opus-1M robustness add-on (+$2 800 – $5 200).**  Out of the current pre-registration; would disambiguate Alt-1 vs Alt-2 (§9 alternatives).  Strongly recommended as a follow-up if H1 is significant on the lightweight panel — but not required for the current product claim.  User to decide whether to fund as part of this protocol or defer to a follow-up paper.
3. **Gemini 2.0 Flash deprecation (2026-06-01).**  If Stage 2 fires after that date, switch to Gemini 2.5 Flash and re-snapshot pricing.  User to confirm migration plan.
4. **BEAM dataset license / redistribution.**  We must confirm the BEAM-10M chat content can be sent to Anthropic, OpenAI, and Google APIs.  Tavakoli et al. 2026 published on HuggingFace; license terms govern re-transmission.  **Required before Stage 1 fires.**
5. **Human-rater recruitment for the κ-validation slice.**  100 items × 3 raters × ~2 min/item = 10 person-hours.  User to identify raters.  Without this, the κ-gate cannot be evaluated.
6. **PII / chat-content scrub.**  BEAM is synthetic but character-driven.  Re-transmission to commercial APIs may need scrubbing.  **Curie audit item before Stage 1.**

## 15. Appendices (committed alongside this file at freeze)

- **Appendix A — Answer-generation prompt (verbatim).**  File: `benchmarks/llm_head_to_head/prompts/answer.md`.  SHA-256 in §10 manifest.
- **Appendix B — Judge prompt (verbatim).**  File: `benchmarks/llm_head_to_head/prompts/judge.md`.  SHA-256 in §10 manifest.
- **Appendix C — Per-condition retrieval call signatures.**  File: `benchmarks/llm_head_to_head/retriever_baselines.py` (B), `benchmarks/llm_head_to_head/cortex_caller.py` (C), `benchmarks/llm_head_to_head/oracle_loader.py` (D), `benchmarks/llm_head_to_head/long_context_truncator.py` (A).

Each appendix is a separate file owned by the engineer agent; this protocol locks their hashes, not their text.

---

## Sources

- Tavakoli, M., et al. (2026). *BEAM: Benchmarking Episodic and Associative Memory in long-context LLMs*. ICLR.  arXiv:2510.27246.  (Item count, ability taxonomy, LIGHT protocol.)
- McNemar, Q. (1947). *Note on the sampling error of the difference between correlated proportions or percentages*. Psychometrika 12:153–157.  (Primary test.)
- Connor, R. J. (1987). *Sample size for testing differences in proportions for the paired-sample design*. Biometrics 43:207–211.  (Power formula.)
- Efron, B. (1979). *Bootstrap methods: another look at the jackknife*. Annals of Statistics 7(1):1–26.  (Paired bootstrap.)
- Holm, S. (1979). *A simple sequentially rejective multiple test procedure*. Scandinavian Journal of Statistics 6(2):65–70.  (Family-wise correction.)
- Liu, N. F., et al. (2023). *Lost in the Middle: How Language Models Use Long Contexts*. TACL.  (Justification for condition A's truncation rule and the strategic-ordering enrichment in C.)
- Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS.  (Condition B reference architecture.)
- Landis, J. R. & Koch, G. G. (1977). *The measurement of observer agreement for categorical data*. Biometrics 33:159–174.  (κ ≥ 0.70 substantial-agreement threshold.)
- Popper, K. (1959). *The Logic of Scientific Discovery*. Routledge.  (Falsifiability framing of §9.)
- Cortex prior work: `docs/papers/thermodynamic-memory-vs-flat-importance.md`; `docs/arxiv/main.tex` §BEAM-10M (assembler MRR 0.471 vs flat 0.353).

---

# One-page summary — slim version, today (rewritten 2026-04-30)

**If we ran the slim version (Haiku 4.5, all 4 conditions, all 196 BEAM-10M items, judged by GPT-4o) today:**

The strongest claim available is **H1**: *Cortex+Haiku-4.5 beats naive-long-context+Haiku-4.5 on BEAM-10M LLM-judged accuracy by ≥10 pp at α=0.01 (paired McNemar).*

Why H1 at the lightweight tier is the right strongest claim:

1. **It matches the deployed product** — Cortex serves 1500 users on the lightweight tier.
2. **Power.**  At p_disc ≈ 0.30–0.45 (higher than v1's Sonnet-tier estimate due to Haiku's larger answer-quality variance), n=196 yields MDE ~9–11 pp at α=0.01 / power 0.80.  Pre-registered +10 pp inside detectable band; pilot will refine.
3. **Mechanism contrast preserved.**  A is no-retrieval, C is full Cortex stack — same generator, same prompt, same items.
4. **Falsifiability preserved** — same clean refutation rule (C ≤ A + 2 pp) at the lightweight tier.

**Confidence statement.**  Conditional on the §11 anti-cheating audit and the §4 judge κ ≥ 0.70 gate passing, we expect to detect H1 in the predicted direction with **moderate confidence (~60–65%)** — slightly below v1's Sonnet-tier estimate (~70%) because Haiku's accuracy ceiling is lower and may compress dynamic range.  H2 likely directional but not significant at α=0.01 without panel-pooling.  H3 expected to fall in the "headroom remains" outcome (D > C by 5–15 pp).

**Cost vs v1.**  Slim is **$40–$60** (was $110–$180).  Full panel is **$65–$130** (was $2 800–$5 200).  Full panel is now affordable as the default deliverable.

If the user can fund only one stage, run the full panel — it costs roughly what v1's slim cost, and answers strictly more questions.

# Three risks this protocol does NOT yet address (next research-scientist hand-off)

1. **Per-ability stratification of the H tests.**  This protocol pre-registers Hs at the *aggregate* level (mean accuracy across all 196 items).  But BEAM's 10 abilities have very different baselines (LIGHT shows abstention ≈ 0.75, contradiction-resolution ≈ 0.05).  An aggregate H1 win could be driven entirely by one or two abilities while Cortex *regresses* on others — a Simpson's-paradox risk.  The protocol reports per-ability accuracies as descriptive but does not pre-register per-ability tests.  Next research-scientist should design a per-ability factorial pre-registration (10 abilities × 3 hypotheses = 30 tests with a stricter Holm correction) — but only after this protocol's aggregate results land, to avoid p-hacking by post-hoc stratification.

2. **Generator-judge collusion.**  The judge is Claude Opus, and one of the generators is also Claude Opus (1M variant).  Even with shuffled answer order and blinded condition labels, Opus may systematically favour answers in its own house style — a bias documented for self-evaluation in Zheng et al. 2023, *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, NeurIPS.  The κ-validation slice catches gross miscalibration but not subtle in-family preference.  Mitigation would be a second judge (e.g. GPT-4o-as-judge) on the same 100-item slice, treating systematic generator-judge same-vendor agreement vs cross-vendor disagreement as a bias diagnostic.  Out of scope for this protocol; flagged for next research-scientist.

3. **BEAM ground-truth reliability.**  BEAM's gold answers and `source_chat_ids` were generated by the BEAM authors' pipeline (Tavakoli et al. 2026), which itself uses LLMs.  We treat BEAM gold as ground truth, but if the BEAM gold is wrong (e.g. an "abstention" item is actually answerable from a turn the BEAM authors missed), our judge will mark a *correct* candidate as wrong.  This contaminates all four conditions equally, so it does not bias H1/H2/H3 directionally — but it lowers absolute accuracies and shrinks the available signal range.  We have no current instrument to measure BEAM gold-error rate.  Next research-scientist could budget a 50-item human spot-check of the BEAM gold itself (separate from the §4 κ slice, which validates the judge against gold rather than gold against truth).

---

End of protocol.  Pre-registration freezes on commit landing this file plus the four appendix files.  Modifications after freeze require addendum files; this protocol is not edited.
