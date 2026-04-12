---
name: security-audit
description: >
  Deep security audit: threat modeling, attack surface enumeration, adversarial perspective,
  dependency audit, secret management, Kerckhoffs test, failure modes under attack,
  antifragility check, and prioritized findings.
category: engineering
trigger: >
  When shipping to production; when handling user data; when "is this secure?" hasn't been
  answered with evidence; when a new attack surface is introduced.
agents:
  - rejewski
  - boyd
  - hamilton
  - taleb
  - wu
shapes: [adversarial-perspective, black-box-reconstruction, graceful-degradation, antifragile, assumption-inventory]
input: System or component to audit. Architecture diagrams. Dependency manifest. Deployment topology.
output: Security audit report with threat model, findings, dependency audit, and prioritized recommendations.
zetetic_gate:
  logical: "Every finding has a reproducible attack vector, not just a theoretical risk"
  critical: "Kerckhoffs test applied — security never depends on obscurity"
  rational: "Findings ranked by impact × exploitability, not just severity labels"
  essential: "The audit covers what the attacker would actually target, not a compliance checklist"
composes: []
aliases: [security, audit, threat-model, pentest]
hand_off:
  needs_hardening: "/design-for-failure — hamilton: graceful degradation under attack"
  needs_implementation: "/implement — engineer builds the fixes"
  needs_monitoring: "/deploy — monitoring for attack detection"
---

## Procedure

### Phase 1: Threat Modeling
1. **Identify assets.** What data, services, and capabilities does the system protect?
   Classify by sensitivity: public, internal, confidential, restricted.
2. **Identify threat actors.** Opportunistic attacker, targeted attacker, malicious insider,
   supply chain compromise. What are their capabilities and motivations?
3. **STRIDE analysis.** For each component, assess: Spoofing, Tampering, Repudiation,
   Information disclosure, Denial of service, Elevation of privilege.

### Phase 2: Attack Surface Enumeration
4. **Entry point audit.** For each entry point (API endpoint, UI form, file upload, admin
   interface, webhook, dependency boundary): assess authentication, authorization, input
   validation, rate limiting, and error information leakage.
5. **rejewski: black-box reconstruction.** Reconstruct the attacker's view of the system.
   What can be discovered from the outside? What does the public interface reveal about
   internal structure?

### Phase 3: Adversarial Analysis
6. **boyd: adversarial tempo.** How fast can an attacker iterate their OODA loop against
   this system? Where are the slow points in the defender's response? Can the attacker
   move faster than the defender can detect and respond?
7. **Dependency audit.** Check all dependencies for known CVEs, supply chain risks,
   abandoned or unmaintained packages, and excessive permissions.
8. **Secret management.** Verify: no secrets in code or version control, environment
   variables properly scoped, rotation possible and tested, secrets encrypted at rest.

### Phase 4: Structural Tests
9. **Kerckhoffs test.** Assume the attacker knows the entire system design, source code,
   and architecture. Does security still hold? If security depends on obscurity at any
   point, flag it as a critical finding.
10. **hamilton: failure modes under attack.** What happens when each defense fails? Does
    the system fail open (dangerous) or fail closed (safe)? What is the degraded state
    when under active attack?
11. **taleb: antifragility check.** Can any attack vector actually improve the system?
    Rate limiting that triggers auto-scaling, brute force that triggers account lockout
    and alerting, port scanning that improves firewall rules.
12. **wu: assumption inventory.** What security assumptions are untested? "Nobody would
    try that." "That endpoint isn't publicly known." "The firewall handles that."

### Phase 5: Prioritization
13. **Rank findings.** Score each finding by impact (what damage if exploited) ×
    exploitability (how easy to exploit). Rank by this product, not by severity label.
14. **Remediation roadmap.** For each finding: specific fix, effort estimate, and
    what defense layer it strengthens.

## Output Format

```
## Security Audit Report: [system/component]

### Threat Model
| Asset | Threat actor | Attack vector | STRIDE category |
|-------|-------------|---------------|-----------------|

### Attack Surface
| Entry point | Auth? | AuthZ? | Input validation? | Rate limited? | Risk |
|-------------|-------|--------|-------------------|---------------|------|

### Findings
| # | Severity | Category | Description | Exploitability | Remediation |
|---|----------|----------|-------------|----------------|-------------|

### Dependency Audit
| Package | Version | Known CVEs | Maintained? | Risk |
|---------|---------|------------|-------------|------|

### Kerckhoffs Test
- System design assumed secret: [list any]
- Security if design is public: [pass/fail with details]

### Untested Assumptions (wu)
| Assumption | Evidence for/against | Risk if false |
|------------|---------------------|---------------|

### Recommendations (priority-ordered by impact × exploitability)
| Priority | Finding | Fix | Effort | Defense layer strengthened |
|----------|---------|-----|--------|---------------------------|
```
