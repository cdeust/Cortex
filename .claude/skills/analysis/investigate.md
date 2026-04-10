---
name: investigate
description: >
  Structured investigation of an anomaly or failure, routing to the appropriate genius
  agents by problem shape.
category: analysis
trigger: >
  When something unexpected happened and the cause is unknown; when a metric moved and
  nobody knows why; when an incident occurred and root-cause analysis is needed.
agents:
  - orchestrator
shapes: []
input: Description of the anomaly. What was expected vs. what was observed.
output: Investigation report with root cause, evidence, and recommendations.
zetetic_gate:
  logical: "The investigation must be structured, not ad-hoc"
  critical: "Every conclusion must be backed by measurement, not by narrative"
  rational: "Route to the right shape — don't force a method that doesn't fit"
  essential: "Answer the question asked; stop when the cause is found"
composes: [estimate, isolate-signal, audit-integrity]
aliases: [investigate-anomaly, rca, root-cause-analysis]
hand_off:
  performance_issue: "/performance-investigation — fermi→curie→knuth"
  data_anomaly: "/anomaly-to-explanation — mcclintock→curie→shannon"
  institutional_resistance: "/statistical-intervention — semmelweis→fisher→feynman"
---

## Procedure

1. **State expected vs observed.** What should have happened? What did happen? Quantify both.
2. **Classify the shape.** The orchestrator identifies which problem shape fits:
   - Measured > predicted from known parts → curie (residual with a carrier)
   - Slow phenomenon, snapshots misleading → darwin (long-horizon observation)
   - Matched groups with different outcomes → semmelweis (statistical anomaly)
   - Aggregate smooth but one case is weird → mcclintock (single-specimen)
   - System slow → fermi→curie→knuth (performance investigation)
3. **Route.** Invoke the appropriate genius agent(s) for the identified shape.
4. **Report.** Root cause, evidence chain, confidence, recommendations.

## Output Format

```
## Investigation: [anomaly name]
### Expected: [what should have happened, quantified]
### Observed: [what did happen, quantified]
### Shape identified: [which problem shape]
### Agent(s) invoked: [which genius agents and why]
### Root cause: [identified, with evidence]
### Confidence: [how sure, what would change the verdict]
### Recommendations: [specific actions]
```
