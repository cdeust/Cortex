---
name: secure
description: >
  Security audit with threat modeling, OWASP check, supply-chain review, and
  defense-in-depth analysis. Every finding cites the vulnerability class and CWE.
category: engineering
trigger: >
  When code handles user input, auth, payments, or sensitive data; when a new dependency
  is added; when a security review is needed before shipping; when an incident suggests
  a vulnerability.
agents:
  - security-auditor
  - engineer
shapes: []
input: Code, config, or architecture to audit. Scope (full audit / targeted review / incident response).
output: >
  Security report: threat model, findings by severity with CWE/OWASP, remediation plan.
zetetic_gate:
  logical: "Every finding must cite the CWE or OWASP category"
  critical: "Verify findings with a reproduction, not just static analysis"
  rational: "Severity by actual exploitability, not theoretical risk"
  essential: "Critical findings first; informational findings last"
composes: []
aliases: [security, audit-security, pentest]
hand_off:
  needs_experiment: "/experiment — fisher: design a controlled security test"
  needs_architecture_change: "/decompose — architect restructures for defense-in-depth"
---

## Procedure

1. **Threat model.** Identify assets, trust boundaries, threat actors, attack surfaces.
2. **OWASP Top 10 check.** For each applicable category: injection, auth, exposure, XXE, access control, misconfig, XSS, deserialization, components, logging.
3. **Supply chain.** Review dependencies for known vulnerabilities, unmaintained packages, typosquatting.
4. **Defense-in-depth.** For each critical path: how many layers of defense? If one fails, what is the blast radius?
5. **Finding verification.** For each finding, attempt reproduction or cite the specific code path. Static-analysis-only findings are marked as unverified.
6. **Report.** Findings by severity (Critical > High > Medium > Low > Info), each with CWE, reproduction, and remediation.

## Output Format

```
## Security Audit: [scope]

### Threat model
[Assets, boundaries, actors, surfaces]

### Findings
| # | Severity | CWE | Description | File:Line | Verified? | Remediation |
|---|----------|-----|-------------|-----------|-----------|-------------|

### Supply chain
| Dependency | Version | Known CVEs | Maintained? | Action |
|------------|---------|------------|-------------|--------|

### Defense-in-depth
| Critical path | Layers | Single point of failure? |
|---------------|--------|-------------------------|
```
