---
name: lab-notebook
description: >
  Structured research lab notebook management. Every meaningful research action gets
  an entry: experiment runs, literature findings, failed approaches, hypothesis
  revisions, benchmark results. Negative results are mandatory. Entries link to
  git commits, provenance files, and difficulty book entries.
category: research
trigger: >
  When running a research campaign with multiple experiments; when "what did we try
  last week?" has no answer; when negative results keep getting lost; when a research
  arc needs to be resumed after a break.
agents:
  - darwin
  - deming
  - feynman
shapes: [no-source-no-implementation, replicate-to-estimate-variance, instrument-before-hypothesis]
input: Research context. Current objective. Notebook location (default: .lab-notebook.md).
output: Structured lab notebook with timestamped entries, tags, cross-references, and timeline view.
zetetic_gate:
  logical: "Every entry has a timestamp, a clear result, and a next-step — no dangling threads"
  critical: "Negative results are recorded with the same rigor as positive results"
  rational: "Entries are written immediately after the action, not retroactively reconstructed"
  essential: "The notebook is the single source of truth for the research arc — if it's not here, it didn't happen"
composes: []
aliases: [notebook, research-log, experiment-log]
hand_off:
  pattern_emerging: "/explain — write up the findings when a clear pattern emerges"
  stuck: "/deep-research — literature review for new hypotheses"
  result_surprising: "/difficulty-book — log the contradiction for long-horizon observation"
---

## Procedure

### Phase 1: Initialize (feynman)

1. **feynman: establish the notebook.** Create or locate the lab notebook file.
   Default: `.lab-notebook.md` in the project root.
2. **Write the research header.** Objective, start date, team, success criteria.
3. **feynman: integrity rules.** The notebook is append-only during a session. Entries are
   never deleted or retroactively modified. Corrections are new entries that reference
   the original. This is the scientific record.

### Phase 2: Entry Structure

4. **Every entry follows this structure:**
   ```
   ### [YYYY-MM-DD HH:MM] [tag1, tag2] — [one-line summary]
   **Objective:** What were we trying to learn or achieve?
   **Method:** What did we do? (brief, reproducible)
   **Result:** What happened? (data, not interpretation)
   **Interpretation:** What does this mean?
   **Next step:** What follows from this?
   **References:** [commit SHA] [provenance file] [difficulty book entry] [prior entry #]
   ```

### Phase 3: When to Write (deming)

5. **deming: PDSA triggers.** Write an entry after each of these events:
   - Experiment run (benchmark, test, measurement) — regardless of outcome
   - Literature finding (paper discovered, source evaluated)
   - Failed approach (code that did not work, hypothesis falsified)
   - Hypothesis revision (updating beliefs based on evidence)
   - Benchmark result (any quantitative measurement)
   - Design decision (architectural choice with rationale)
   - Session start (resuming work — summarize where we left off)
   - Session end (what was accomplished, what is next)
6. **Immediacy rule.** Write the entry within minutes of the event. Memory degrades.
   Do not batch entries at end-of-day.

### Phase 4: Negative Results (darwin)

7. **darwin: negative results are mandatory.** Every revert, dead end, failed hypothesis,
   and negative benchmark result gets a full entry. Tag: `negative-result`.
8. **Why it failed.** Not just "it didn't work" but: what was the hypothesis, what was
   observed, what does this rule out, what does this suggest instead?
9. **darwin: difficulty book linkage.** If the negative result is surprising (contradicts
   theory or expectation), also create a difficulty book entry and cross-reference it.
10. **No silent reverts.** If code is reverted, the notebook records: what was tried, what
    was measured, why it was reverted, and the revert commit SHA.

### Phase 5: Cross-References and Linking

11. **Git commits.** Every entry that involves a code change includes the commit SHA.
    Format: `[commit: abc1234]`.
12. **Provenance files.** If sources were consulted, link to the relevant .provenance.md.
    Format: `[provenance: path/to/file.provenance.md]`.
13. **Difficulty book.** If a contradiction was found, link to the difficulty book entry.
    Format: `[difficulty: #entry-id]`.
14. **Prior entries.** Reference earlier notebook entries that this builds on.
    Format: `[notebook: #entry-number]`.

### Phase 6: Search and Navigation

15. **Tags.** Every entry has at least one tag from a controlled vocabulary:
    `experiment`, `literature`, `negative-result`, `hypothesis`, `benchmark`,
    `design-decision`, `session-start`, `session-end`, `correction`.
16. **Search by tag.** Use `lab-notebook-manager.sh search --tag <tag>`.
17. **Search by date range.** Use `lab-notebook-manager.sh search --from <date> --to <date>`.
18. **Search by keyword.** Use `lab-notebook-manager.sh search --keyword <term>`.

### Phase 7: Timeline and Session Boundaries

19. **Timeline view.** Chronological summary of the research arc. Each entry compressed to
    one line: date, tag, summary, result direction (positive/negative/neutral).
    Use `lab-notebook-manager.sh timeline`.
20. **Session boundaries.** Mark session starts and ends explicitly so long-running research
    can be resumed. Session start entries summarize: where we left off, what is the current
    best-known result, what is the next planned step.
21. **Arc summary.** At the end of a research campaign, write a final entry summarizing:
    total iterations, best result, key lessons, open questions.

## Output Format

```
## Lab Notebook: [research objective]
### Started: [date] | Status: [active / paused / complete]
### Success criteria: [what constitutes "done"]

---

### #001 [2025-01-15 09:00] [session-start] — Begin optimization of retrieval latency
**Objective:** Reduce p95 retrieval latency below 50ms
**Method:** Session initialization, reviewing prior work
**Result:** Baseline is 120ms p95 (commit: abc1234)
**Interpretation:** 2.4x improvement needed
**Next step:** Profile to find bottleneck
**References:** [commit: abc1234]

### #002 [2025-01-15 09:30] [experiment, negative-result] — Batch size increase to 64
**Objective:** Test if larger batch size reduces per-query latency
**Method:** Changed BATCH_SIZE from 16 to 64, ran benchmark suite (N=10)
**Result:** p95 latency increased to 145ms (+21%)
**Interpretation:** Memory pressure from larger batches causes GC pauses
**Next step:** Try reducing allocation, not increasing batch size
**References:** [commit: def5678] [notebook: #001]

---

### Timeline:
| # | Date | Tag | Summary | Direction |
|---|------|-----|---------|-----------|

### Session log:
| Session | Start | End | Entries | Key result |
|---------|-------|-----|---------|------------|
```
