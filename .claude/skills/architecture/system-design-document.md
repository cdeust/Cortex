---
name: system-design-document
description: >
  Complete system design document: requirements, architecture, component design, data model,
  API contracts, failure modes, scaling analysis, security, deployment, and open questions.
  Every section uses a domain expert agent for rigor.
category: architecture
trigger: >
  When building a new system or major feature; when the design exists only in someone's head;
  when "how does this work at 100x?" hasn't been answered; when starting a project that
  multiple engineers will work on.
agents:
  - rawls
  - le-guin
  - alexander
  - beer
  - lavoisier
  - al-khwarizmi
  - liskov
  - panini
  - hamilton
  - thompson
  - erlang
  - deming
  - darwin
  - wu
shapes: [pattern-language, viability, conservation, canonical-form, substitutability, graceful-degradation, scale-break, difficulty-book]
input: Problem statement. Stakeholders. Known constraints. Scale expectations.
output: Complete design document suitable for team review and implementation.
zetetic_gate:
  logical: "Architecture layers have no circular dependencies; component responsibilities do not overlap"
  critical: "Scaling analysis identifies concrete break points, not just 'it scales'"
  rational: "Design complexity is proportional to problem complexity — no over-engineering"
  essential: "Open questions and difficulty book are populated honestly, not left empty"
composes: [spec, contract, decompose]
aliases: [design-doc, system-design, architecture-doc, tech-design]
hand_off:
  needs_spec: "/spec — lamport: formal specification for concurrent/distributed components"
  needs_resilience: "/design-for-failure — hamilton: failure mode design"
  needs_security: "/security-audit — rejewski: deep security audit"
  ready_to_implement: "/implement — engineer builds it"
---

## Procedure

### Phase 1: Requirements (rawls, le-guin)
1. **rawls: stakeholder fairness.** Identify all stakeholders. Ensure requirements reflect
   all affected parties, not just the loudest voice. Apply the veil of ignorance: would
   this design be acceptable to any stakeholder?
2. **le-guin: honest trade-off naming.** Name every trade-off explicitly. No "we get X
   for free" — everything has a cost. Document what is sacrificed for each choice.
3. **Functional requirements.** What the system must do. Acceptance criteria for each.
4. **Non-functional requirements.** Latency, throughput, availability, consistency,
   durability, security. With specific numbers, not "fast" or "reliable."
5. **Constraints.** Technology, budget, timeline, team, regulatory, compatibility.

### Phase 2: Architecture (alexander, beer)
6. **alexander: pattern language.** Identify the architectural patterns that fit this
   problem. Name them. Justify why each pattern was chosen over alternatives.
7. **beer: VSM completeness.** Verify the architecture has all five viable system model
   functions: operations, coordination, control, intelligence, policy. Missing functions
   become blind spots.
8. **Component diagram.** High-level components, their responsibilities, and interactions.
   Each component has exactly one responsibility domain.

### Phase 3: Component Design
9. **For each major component:** interface (what it exposes), behavior (what it does),
   data model (what it owns), failure modes (how it breaks), dependencies (what it needs).
10. **lavoisier: data conservation.** Verify nothing is created from nothing or destroyed
    silently. Every data flow is accounted for: input, transformation, output, error path.
11. **al-khwarizmi: canonical form.** Schema design with normalization justification.
    Every entity has one canonical representation. Denormalization is justified by
    measured performance need, not premature optimization.

### Phase 4: API Contracts (liskov, panini)
12. **liskov: substitutability.** Every interface is designed so implementations are
    substitutable. No method throws "not implemented." No caller checks concrete type.
13. **panini: grammar consistency.** API naming, parameter ordering, error format, and
    pagination follow a single consistent grammar across all endpoints.
14. **Behavioral contracts.** For each API: preconditions, postconditions, invariants,
    error semantics, idempotency guarantees.

### Phase 5: Failure and Scale (hamilton, thompson, erlang)
15. **hamilton: failure modes and resilience.** For each component: what fails, how it
    degrades, recovery path, restart granularity. The degraded state is designed, not
    accidental.
16. **thompson: scale-break analysis.** Where does this break at 10x? 100x? 1000x?
    Identify the first bottleneck at each scale. Name the scaling strategy for each.
17. **erlang: queuing analysis.** For request-processing components: arrival rate,
    service rate, queue depth, latency distribution. Where does queuing blow up?

### Phase 6: Security and Operations (deming)
18. **Security considerations.** Trust boundaries, authentication, authorization, data
    classification. Reference /security-audit for deep analysis.
19. **deming: operational excellence.** Deployment strategy, monitoring, alerting, runbook
    pointers. How does the on-call engineer diagnose problems at 3 AM?
20. **Observability.** What metrics, logs, and traces are emitted? Are they sufficient
    to diagnose the failure modes identified in Phase 5?

### Phase 7: Open Questions (darwin, wu)
21. **darwin: difficulty book.** What is hard about this design? What are the hardest
    objections? Document them honestly — do not minimize.
22. **wu: assumption inventory.** What assumptions is this design built on? Which are
    tested, which are untested? What happens if each untested assumption is wrong?
23. **Open questions.** What remains unresolved? What needs prototyping? What needs
    expert input?

## Output Format

```
## System Design: [name]

### 1. Requirements
#### Stakeholders: [who is affected]
#### Trade-offs: [what is sacrificed for what]
#### Functional: [requirements with acceptance criteria]
#### Non-functional: [with specific numbers]
#### Constraints: [technology, budget, timeline, team, regulatory]

### 2. Architecture
#### Patterns: [name, justification, alternatives considered]
#### VSM completeness: [operations, coordination, control, intelligence, policy]
#### Component diagram: [components, responsibilities, interactions]

### 3. Component Design
| Component | Interface | Behavior | Data model | Failure modes | Dependencies |
|-----------|-----------|----------|------------|---------------|-------------|

### 4. Data Model
#### Schema: [entities, relationships, normalization level]
#### Data flows: [input → transform → output, with error paths]

### 5. API Contracts
| Endpoint | Preconditions | Postconditions | Errors | Idempotent? |
|----------|--------------|----------------|--------|-------------|

### 6. Failure Modes
| Component | Failure | Degraded behavior | Recovery | Restart granularity |
|-----------|---------|-------------------|----------|---------------------|

### 7. Scaling Analysis
| Scale | First bottleneck | Strategy | Queuing risk |
|-------|-----------------|----------|-------------|

### 8. Security: [trust boundaries, auth, data classification]

### 9. Operations
#### Deployment: [strategy, rollback]
#### Monitoring: [metrics, alerts, thresholds]
#### Runbook pointers: [diagnostic paths for common failures]

### 10. Open Questions and Difficulty Book
#### Difficulty book: [hardest problems, honest assessment]
#### Untested assumptions: [assumption, consequence if wrong]
#### Unresolved: [questions requiring further work]
```
