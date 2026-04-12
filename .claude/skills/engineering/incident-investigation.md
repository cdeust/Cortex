---
name: incident-investigation
description: >
  Structured incident postmortem: timeline reconstruction, three-timescale decomposition,
  root cause chain, archetype identification, remediation design, and prevention verification.
  Human error is NEVER the root cause — keep going until you find the system failure.
category: engineering
trigger: >
  When an incident has occurred; when a postmortem is needed; when "it was human error" is the
  current explanation; when the same class of incident keeps recurring.
agents:
  - ginzburg
  - braudel
  - deming
  - arendt
  - peirce
  - meadows
  - hamilton
  - maxwell
shapes: [forensic-trace, multi-timescale, systemic-cause, feedback-design, graceful-degradation]
input: Incident description. Available logs, metrics, alerts, communications. Known impact.
output: Incident report with timeline, root cause chain, archetype, remediation, and prevention plan.
zetetic_gate:
  logical: "Root cause chain is traceable from symptom to structural failure without gaps"
  critical: "Every claim in the timeline is sourced from logs, metrics, or communications — not memory"
  rational: "Remediation addresses the structural cause, not just the proximate trigger"
  essential: "Human error is never accepted as root cause; the system that allowed it is"
composes: []
aliases: [postmortem, incident, rca, root-cause]
hand_off:
  needs_resilience_design: "/design-for-failure — hamilton: redesign the failure mode"
  needs_monitoring: "/deploy — maxwell: monitoring and feedback design"
  systemic_issue: "/evaluate-tool — meadows: system archetype intervention"
---

## Procedure

### Phase 1: Forensic Reconstruction (ginzburg)
1. **ginzburg: timeline reconstruction.** Build a precise timeline from logs, metrics, alerts,
   and communications. Every entry has a timestamp and source. No entry from memory alone.
2. **ginzburg: trace anomalies.** Identify the marginal clues — the small signals that preceded
   the incident. What was different from normal operation?

### Phase 2: Three-Timescale Decomposition (braudel)
3. **braudel: event level.** What happened? The sequence of actions and failures.
4. **braudel: conjuncture level.** What conditions enabled it? Staffing, deployment timing,
   technical debt, recent changes, organizational pressure.
5. **braudel: structural level.** What systemic factors made this class of incident possible?
   Architecture, incentive structures, missing feedback loops, institutional patterns.

### Phase 3: Classification (deming, arendt)
6. **deming: common vs special cause.** Is this a systemic issue (common cause — the system
   regularly produces this kind of failure) or a one-off (special cause — an unusual event)?
   Common cause requires system redesign. Special cause requires a specific fix.
7. **arendt: thoughtlessness audit.** Was this caused by someone not thinking, or by a process
   that made thinking unnecessary? Does the system reward speed over care? Are operators
   expected to be vigilant without the tools to be vigilant?

### Phase 4: Root Cause Chain (peirce, meadows)
8. **peirce: abductive root cause chain.** Trace from symptom through proximate causes to
   structural root cause. At each level, apply abduction: what is the simplest explanation
   that accounts for all observed evidence? Apply "five whys" but insist that human error
   is NEVER the root cause — keep going until you find the system failure.
9. **meadows: archetype identification.** Does this incident match a system archetype?
   - Shifting the burden (workaround became the norm)
   - Eroding goals (standards gradually lowered)
   - Escalation (competing pressures amplified)
   - Fixes that fail (previous fix created this problem)
   - Tragedy of the commons (shared resource degraded)

### Phase 5: Remediation (hamilton, maxwell)
10. **hamilton: remediation design.** Fix the structural cause, not just the proximate trigger.
    Design the fix so that failure of the fix itself is safe. Verify the fix does not
    introduce new failure modes.
11. **maxwell: prevention verification.** Design the feedback loop that detects this BEFORE it
    becomes an incident. What signal to monitor? What threshold? What automated response?

## Output Format

```
## Incident Report: [title]

### Timeline
| Time | Event | Source |
|------|-------|--------|

### Three-timescale analysis
- **Event level:** [what happened]
- **Conjuncture:** [what conditions enabled it]
- **Structure:** [what systemic factors made it possible]

### Root cause chain
trigger → proximate cause → contributing factors → structural root cause

### Archetype: [name if applicable, with evidence]

### Common vs special cause: [classification with evidence]

### Thoughtlessness audit: [was thinking suppressed? how?]

### Remediation
| Action | Addresses | Level (event/conjuncture/structure) | Owner |
|--------|-----------|-------------------------------------|-------|

### Prevention
| Signal to monitor | Detection method | Agent for ongoing monitoring |
|-------------------|------------------|------------------------------|
```
