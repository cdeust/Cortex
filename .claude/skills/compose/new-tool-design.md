---
name: new-tool-design
description: >
  Design a new tool: augmentation framing (engelbart), abstraction barrier (hopper),
  runtime malleability (kay), integrated experience (jobs).
category: compose
trigger: >
  When building a new tool, library, SDK, or developer experience from scratch;
  when the question is "what should this tool be?" not just "how do we build it."
agents:
  - engelbart
  - hopper
  - kay
  - jobs
shapes: [augment-not-automate, compile-as-abstraction-barrier, late-binding, runtime-malleability, integrated-experience-as-spec]
input: The problem the tool solves. The target users. The deployment context.
output: Tool design with augmentation framing, abstraction layer, malleability plan, experience spec.
zetetic_gate:
  logical: "H-LAM/T components must be coherent as a system"
  critical: "Demo the key capability live; don't just describe it"
  rational: "Augment vs automate is a deliberate choice, not a default"
  essential: "The tool AND the work practice co-evolve — design both"
composes: [augment-workflow, build-abstraction, defer-decisions, audit-experience]
aliases: [design-tool, tool-design, build-tool]
hand_off:
  needs_spec: "/spec — lamport: if the tool has concurrent behavior"
  needs_contracts: "/contract — liskov: if the tool has plugin boundaries"
  needs_implementation: "/implement — engineer builds it"
---

## Procedure

### Phase 1: Augmentation frame (engelbart)
1. engelbart: what human work is being augmented? What does the human uniquely contribute?
2. engelbart: H-LAM/T inventory: Human, Language, Artifacts, Methodology, Training — design all five.
3. engelbart: bootstrap plan — the team building the tool must use the tool.
4. engelbart: ceiling AND floor — expert capability AND novice onboarding.

### Phase 2: Abstraction barrier (hopper)
5. hopper: what is the user's vocabulary? What is the implementation's?
6. hopper: design the compiler/translator between them.
7. hopper: debugging is first-class — build observability into the tool.

### Phase 3: Malleability (kay)
8. kay: binding audit — what decisions can be deferred to runtime?
9. kay: coupling audit — where should messaging replace procedure calls?
10. kay: is this an application or an environment? Can the user modify it?

### Phase 4: Integration (jobs)
11. jobs: experience spec — "it just works" at every user contact point.
12. jobs: seam audit — no visible integration boundaries.
13. jobs: edit — remove everything that doesn't serve the experience.

## Output Format

```
## Tool Design: [tool name]

### Augmentation frame:
- Human work augmented: [...]
- H-LAM/T: [all five components]
- Bootstrap plan: [how the team uses the tool]
- Ceiling/floor targets: [novice at 1 hour, expert at 1 year]

### Abstraction:
- User vocabulary: [...] → Implementation vocabulary: [...]
- Translator design: [...]
- Debugging: [first-class? how?]

### Malleability:
- Late binding opportunities: [...]
- Messaging boundaries: [...]
- Application or environment: [...]

### Integration:
- Experience spec: [per contact point]
- Seams: [where are they? how to sand them?]
- Edited out: [features removed to serve the experience]
```
