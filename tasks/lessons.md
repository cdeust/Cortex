# Lessons Learned

## 2026-04-03 — Platt Sigmoid Confidence Gate

**Issue**: Binary gate in reranker.py (1.0 above CE threshold, 0.1 below) was replaced with Platt-calibrated sigmoid to provide smooth confidence transitions. Hypothesis: gradual suppression would help BEAM abstention.

**Approaches tried and rejected:**
- Platt sigmoid A=10, B=-1.5 (inflection CE=0.15): BEAM 0.479 (-0.148), LoCoMo R@10 92.6% (-5.1pp), LME flat
- Platt sigmoid A=30, B=-1.5 (inflection CE=0.05): BEAM 0.442 (-0.185) — even worse

**Root cause**: Even 1-5% multiplicative suppression on mid-range CE scores (0.15-0.30) compounds across rankings and pushes correct results down. The binary gate is empirically optimal — valid retrievals need exactly 1.0 confidence, not 0.95. Smooth transitions only help if properly calibrated from held-out data via logistic regression over (max_CE, is_correct) pairs.

**Rule**: Don't replace a tuned binary gate with a hand-tuned sigmoid. Platt scaling requires proper calibration data fit via maximum likelihood, not hand-picked A/B values. The binary gate's harshness is a feature, not a bug.

## 2026-04-02 — Adaptive Retrieval Weights

**Issue**: Static signal weights (fts=0.5, heat=0.3, ngram=0.3) can't optimize across both conversational (BEAM) and factual (LME/LoCoMo) benchmarks simultaneously. BEAM-optimal weights (fts=0, heat=0.7) regress LME by -9.2pp R@10.

**Approaches tried and rejected:**
- Quality gating in PL/pgSQL (count-based signal quality factor) → all 3 benchmarks worse
- Pre-retrieval query specificity (content word ratio, entity count) → features NOT discriminative between BEAM and LME queries (ratio 0.470 vs 0.459)
- Meta-conversational pattern detection → only 20% of BEAM queries match, 10% of LME
- Higher fixed alpha (0.80-1.00) → monotonically worse on BEAM
- Adaptive alpha via CE score spread (Shtok QPP) → LoCoMo -5.1pp R@10

**Rule**: Don't try to adapt signal weights per-query without strong discriminative features. The current balanced weights ARE the empirically justified optimum for mixed workloads. Document failed approaches with data.

## 2026-04-02 — PreToolUse Hook Semantics

**Issue**: Built a preemptive context injection hook assuming PreToolUse exit 0 injects stdout into model context. It does NOT — PreToolUse exit 0 is silent, exit 2 blocks the tool.

**Fix**: Rewrote as PostToolUse heat-priming hook (spreading activation pattern). File access cue boosts heat of related memories so they surface in subsequent recall.

**Rule**: Always verify hook exit code semantics from Claude Code source documentation before building hooks. PreToolUse = validation only. UserPromptSubmit and SessionStart exit 0 = context injection.

## 2026-04-02 — Decision Auto-Protection

**Pattern**: Decisions ("decided to X", "chose Y over Z") are already detected by `memory_decomposer.py` regex and tagged. The missing piece was auto-setting `is_protected=True` + importance boost on these memories.

**Rule**: When a feature already detects something (like decision patterns), wire the downstream action (protection, propagation) immediately. Don't require manual intervention for obvious automation.

## 2026-04-02 — SQLite Checkpoint created_at

**Issue**: `NOT NULL constraint: checkpoints.created_at` on SQLite. Schema has `DEFAULT (datetime('now'))` but older databases may have been created without the default.

**Rule**: Always include timestamp columns explicitly in INSERT statements, even when the schema has a DEFAULT. Don't rely on schema defaults for backward compatibility with older DB files.

## 2026-03-22 — Asyncio Deprecation

**Issue**: `asyncio.get_event_loop()` is deprecated in Python 3.10+.

**Rule**: Never use `asyncio.get_event_loop()`. Use `asyncio.run()` for top-level or `asyncio.get_running_loop()` inside async functions.

## 2026-03-22 — MCP Server Connection

**Rule**: When MCP connection fails, verify the server independently first (`echo initialize | python3 -m mcp_server`) before assuming code bugs.
