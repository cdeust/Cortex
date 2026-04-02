# Cortex — Active Development Plan

**Version:** 3.2.0 (released 2026-04-02)
**Last updated:** 2026-04-03

---

## Axis 1: Seamless UX — "Install and Forget"

Goal: Cortex works invisibly when the plugin is installed. No explicit commands needed.

### Completed
- [x] SessionStart hook — inject anchors + hot memories + team decisions
- [x] PostToolUse capture — auto-store significant actions
- [x] PostToolUse priming — heat-boost related memories on file access
- [x] SessionEnd dream — activity-gated consolidation (light/standard/full)
- [x] Compaction checkpoint — save/restore across context compaction
- [x] SubagentStart briefing — auto-brief agents with prior work + team decisions
- [x] UserPromptSubmit auto-recall — FTS-based memory injection on every message
- [x] Plugin.json registers all 7 hooks automatically

### Next
- [ ] Fix MCP server SQLite fallback — 4 tools fail when PG unavailable (consolidate, add_rule, create_trigger, forget force). The SQLite store has all methods; issue is in server initialization.
- [ ] PostCompact hook — after context compaction, inject richer reconstruction context (anchored decisions + checkpoint + triggered alerts + last 3 remembered items)
- [ ] Auto-seed on first install — detect empty DB + existing project, offer one-click bootstrap without manual `/cortex-setup-project`
- [ ] Reduce tool surface — hide advanced tools (drill_down, navigate_memory, explore_features, etc.) behind `CORTEX_ADVANCED_TOOLS=1` env var. Keep only 8 essential tools visible by default.

---

## Axis 2: Agent Team Integration

Goal: Cortex is the shared brain for a team of specialized agents.

### Completed
- [x] Decision auto-protection — regex detection + is_protected + 1.5x importance (McGaugh 2004, Adcock 2006)
- [x] Team memory bus — protected decisions auto-propagate via is_global (Wegner 1987 TMS)
- [x] Agent briefing hook — SubagentStart injects prior work + team decisions (Smith & Vela 2001)
- [x] Agent topic scoping — agent_context column + recall boost for matching topic
- [x] when_to_use + agent_topic in all 11 agent frontmatter (zetetic-team-subagents)

### Next
- [ ] Agent skills — each specialist agent gets associated slash commands (e.g., researcher gets `/cortex-research`, engineer gets `/cortex-develop`)
- [ ] Conditional skill activation — skills surface only when relevant files are open (Claude Code `paths` frontmatter pattern)
- [ ] Cross-agent conflict detection — when two agents write contradicting decisions, surface the conflict to the orchestrator
- [ ] Agent performance memory — track which agents produce good/bad outcomes, inform future orchestration decisions

---

## Axis 3: Anthropic Research Integration

Goal: Apply Anthropic's published research to improve Cortex's memory mechanisms.

### Emotional Importance Scoring
**Source:** [Emotion Concepts (Anthropic, Apr 2026)](https://www.anthropic.com/research/emotion-concepts-function)
**Finding:** 171 emotion features found in Claude. Emotion vectors causally drive behavior. Positive-valence emotions predict task preference.
**Application:** Extend `emotional_tagging.py` with Anthropic's 171-concept taxonomy for richer importance scoring. Current implementation uses Wang & Bhatt 2024 Yerkes-Dodson; Anthropic's work validates that emotional salience is computationally real, not metaphorical.
- [ ] Map Anthropic's 171 emotion concepts to memory importance weights
- [ ] Use emotion keyword density as a secondary importance signal during ingestion
- [ ] Track emotional trajectory across sessions for narrative engine

### Persona Drift Monitoring
**Source:** [Persona Vectors (Anthropic, Aug 2025)](https://www.anthropic.com/research/persona-vectors)
**Finding:** Extractable activation patterns control character traits. Can detect personality shifts.
**Application:** Our `persona_vector.py` already implements 12D persona vectors. Extend with drift detection alerts — when an agent's behavioral profile shifts significantly, flag it.
- [ ] Add session-over-session drift metric to persona_vector.py
- [ ] Alert orchestrator when agent drift exceeds threshold
- [ ] Store persona snapshots for trend analysis

### Retrieval Attribution
**Source:** [Circuit Tracing (Anthropic, Mar 2025)](https://www.anthropic.com/research/tracing-thoughts-language-model)
**Finding:** Attribution graphs trace multi-step reasoning through model circuits.
**Application:** Our `attribution_tracer.py` does pipeline-level attribution. Extend to explain WHY a memory was retrieved — which signals (vector, FTS, heat, entity) contributed most.
- [ ] Return per-signal contribution scores with recall results
- [ ] Visualize signal attribution in the dashboard detail panel
- [ ] Use attribution data to auto-tune signal weights (closed-loop optimization)

### Salience Self-Tagging
**Source:** [Introspection (Anthropic, Oct 2025)](https://www.anthropic.com/research/introspection)
**Finding:** Claude can sometimes report on its own internal states, including salience tagging (~20% reliable).
**Application:** When capturing PostToolUse, add a lightweight classification step: "is this output worth remembering?" Currently we use keyword heuristics; this would use the model's own salience judgment.
- [ ] Prototype: add prompt-based salience classifier to PostToolUse (measure latency impact)
- [ ] Compare heuristic vs model-based capture quality on benchmark data
- [ ] Only deploy if latency < 2s and quality measurably better

---

## Axis 4: Benchmark Improvement

Goal: Maintain SOTA retrieval scores. Identify and fix weakest categories.

### Current Scores (v3.2.0)
| Benchmark | Metric | Score |
|---|---|---|
| LongMemEval | R@10 | 98.0% |
| LongMemEval | MRR | 0.880 |
| LoCoMo | R@10 | 97.7% |
| LoCoMo | MRR | 0.840 |
| BEAM | MRR | 0.627 |

### Weakest Categories
- BEAM abstention: 0.125 MRR — requires knowing what was NEVER discussed
- BEAM instruction_following: 0.242 MRR — meta-directives semantically distant from queries
- BEAM event_ordering: 0.353 MRR — sequence reconstruction from scattered turns
- LoCoMo temporal: 0.538 MRR — time-based reasoning

### Research Leads
- [ ] Abstention: investigate sufficient context modeling (Joren et al. ICLR 2025) — current binary gate is too simple
- [ ] Instruction following: explore instruction-aware embedding fine-tuning or instruction memory tagging
- [ ] Event ordering: temporal chain extraction at ingest time (store sequence metadata)
- [ ] LoCoMo temporal: enhance date prefix injection and temporal proximity scoring

### Ablation Data (completed, committed)
All results in `benchmarks/beam/ablation_results.json`:
- rerank_alpha: 0.70 optimal (monotonic improvement from 0.30)
- Signal weights: fts=0.0 optimal for BEAM, but regresses LME/LoCoMo
- Adaptive alpha: rejected (LoCoMo -5.1pp R@10)
- Quality gating: rejected (all benchmarks worse)
- Pre-retrieval specificity: not discriminative (BEAM/LME features identical)

---

## Axis 5: UI & Visualization

Goal: Dashboard reflects all v3.2.0 features and is polished for public demo.

### Completed
- [x] Protected nodes: gold wireframe torus ring
- [x] Team/global nodes: agent-colored outer glow
- [x] Detail panel: agent, protected, team badges
- [x] Tooltip: agent + protected + team inline
- [x] Stats bar: protected count, trigger count
- [x] Agent color map: 11 specialist colors

### Next
- [ ] Agent filter — filter graph by agent_topic to see one specialist's memory landscape
- [ ] Team decision timeline — chronological view of auto-protected decisions across agents
- [ ] Memory flow animation — show how memories propagate from agent scope to team scope
- [ ] Consolidation history — visualize dream cycles (when consolidation ran, what was decayed/compressed)
- [ ] Heat heatmap — 2D grid view of all memories colored by current heat (alternative to 3D graph)

---

## Axis 6: Code Quality & Infrastructure

### Test Report Fixes (v3.2.0)
- [x] checkpoint created_at NOT NULL — explicit datetime('now') in SQLite insert
- [x] narrative raw tool names — strip PostToolUse headers before generating stories
- [x] get_methodology_graph 2M chars — cap at 200 nodes / 500 edges
- [x] get_causal_chain 72K chars — default max_edges 200→50
- [ ] 4 tools database_not_connected — improve MCP server PG fallback to SQLite

### Ongoing
- [ ] Refactoring plan — 31 files over 300 lines (see tasks/refactoring-plan.md)
- [ ] Coverage targets — shared 95%+, core 90%+, infrastructure 85%+
- [ ] CI: update GitHub Actions to Node.js 24 (deprecation warning)
