---
name: onboarding-curriculum
description: >
  Design onboarding for a new team member: assess the zone of proximal development
  (Vygotsky), structure as narrative (Bruner), map the domain's pattern language
  (Alexander), and verify with the explain-to-freshman test (Feynman).
category: compose
trigger: >
  When a new team member is joining; when existing onboarding is a link dump with no
  sequence; when someone needs to learn a complex system and the documentation assumes
  expert knowledge.
agents:
  - vygotsky
  - bruner
  - alexander
  - feynman
shapes: [zpd-assessment, narrative-scaffolding, pattern-language, explain-to-freshman]
input: The domain to onboard into, the new member's background, and the target competency level.
output: Sequenced onboarding curriculum with scaffolded exercises, verification checkpoints, and fading schedule.
zetetic_gate:
  logical: "Dependencies between topics must be explicit — no circular prerequisites"
  critical: "Each exercise must have a verifiable success criterion, not 'read and understand'"
  rational: "Sequence must follow ZPD — stretch but not overwhelm"
  essential: "Onboarding ends when the person can do the job, not when they've read the docs"
composes: [explain]
aliases: [onboarding, new-member, ramp-up, learning-plan]
hand_off:
  domain_undocumented: "/adr — document the key decisions first, then onboard"
  knowledge_gap_found: "/explain — feynman explains the concept that has no clear explanation"
---

## Procedure

### Phase 1: Assess Required Knowledge and ZPD (vygotsky)
1. vygotsky: list the knowledge and skills required for the target competency.
2. vygotsky: assess the new member's current level. Identify the zone of proximal development — what they can almost do with guidance.
3. vygotsky: identify the gap. Sequence topics from current level toward target competency.
4. **Gate:** the sequence must respect dependency order. No topic should require knowledge that comes later.

### Phase 2: Structure as Narrative (bruner)
5. bruner: organize the curriculum as a narrative. Each module tells a story: context, challenge, resolution.
6. bruner: spiral structure — revisit key concepts at increasing depth across modules.
7. **Gate:** the narrative must be motivating. Each module answers "why does this matter?" before "how does this work?"

### Phase 3: Map the Pattern Language (alexander)
8. alexander: identify the domain's pattern language — the recurring solutions, idioms, and conventions.
9. alexander: embed patterns in the exercises. The new member should recognize patterns by the end, not just facts.
10. **Gate:** patterns must be named and explicit. "You'll pick it up" is not a pattern language.

### Phase 4: Scaffolded Exercises
11. Design one exercise per module. Each exercise is in the ZPD: challenging but achievable with guidance.
12. Each exercise has a verifiable success criterion (a test passes, a feature works, a review is approved).
13. Plan the fading schedule: reduce guidance over successive modules until the person works independently.

### Phase 5: Verify with Explain-to-Freshman (feynman)
14. feynman: can each module's core concept be explained to a freshman? If not, the module is too dense — split it.
15. **Gate:** every module passes the explain-to-freshman test before inclusion.

## Output Format

```
## Onboarding Curriculum: [domain]
### Target competency: [what they can do at the end]
### Estimated duration: [time]

### ZPD assessment (vygotsky):
Current level: [...]
Target level: [...]
Gap: [...]

### Curriculum:
| Module | Story (bruner) | Patterns (alexander) | Exercise | Success criterion | Guidance level |
|--------|---------------|---------------------|----------|------------------|---------------|

### Fading schedule:
| Module | Guidance provided | Guidance removed |
|--------|------------------|-----------------|

### Explain-to-freshman check (feynman):
| Module | Core concept in plain language | Pass? |
|--------|------------------------------|-------|
```
