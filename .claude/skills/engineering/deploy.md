---
name: deploy
description: >
  Plan a deployment with pipeline, rollback strategy, monitoring, and verification.
category: engineering
trigger: >
  When shipping to staging or production; when a deployment pipeline needs design;
  when "how do we roll this back?" hasn't been answered.
agents:
  - devops-engineer
  - engineer
  - hamilton
shapes: [graceful-degradation, defensive-by-default]
input: What is being deployed. Target environment. Risk assessment.
output: Deployment plan with pipeline steps, rollback strategy, health checks, monitoring.
zetetic_gate:
  logical: "Every deployment step has a rollback"
  critical: "Health checks verify the deployment actually works"
  rational: "Canary/progressive rollout for high-risk changes"
  essential: "Monitoring is set up BEFORE the deployment, not after"
composes: []
aliases: [ship, release]
hand_off:
  needs_resilience_design: "/design-for-failure — hamilton: priority scheduling under failure"
---

## Procedure

1. **hamilton: criticality assessment.** What is the blast radius if this fails? What is the rollback time?
2. **devops-engineer: pipeline design.** Build → test → deploy-to-staging → verify → deploy-to-production. Each step has a gate.
3. **Rollback plan.** For each step: what is the rollback? How long does it take? Is it tested?
4. **Monitoring.** Set up health checks, error-rate alerts, latency alerts BEFORE deploying.
5. **Deploy.** Execute the pipeline. Verify at each gate.
6. **Post-deploy verification.** Health checks pass. Error rate stable. Latency stable. User-facing behavior correct.

## Output Format

```
## Deployment Plan: [what]

### Blast radius: [if it fails, what breaks]
### Pipeline:
| Step | Gate | Rollback | Rollback time |
|------|------|----------|---------------|

### Monitoring (set up BEFORE deploy):
| Signal | Threshold | Alert |
|--------|-----------|-------|

### Post-deploy checklist:
- [ ] Health checks pass
- [ ] Error rate stable
- [ ] Latency stable
- [ ] User-facing smoke test
```
