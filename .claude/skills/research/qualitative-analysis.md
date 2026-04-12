---
name: qualitative-analysis
description: >
  Conduct qualitative analysis: grounded theory (Strauss), thick description (Geertz),
  discourse analysis (Foucault), or hermeneutic interpretation (Gadamer). Select
  approach based on research question, apply rigorously, maintain audit trail.
category: research
trigger: >
  When research data is textual, observational, or experiential and requires systematic
  interpretation; when "we did interviews" but the analysis is impressionistic; when
  qualitative findings need to be defensible under scrutiny.
agents:
  - strauss
  - geertz
  - foucault
  - gadamer
  - peirce
shapes: [grounded-theory, thick-description, discourse-analysis, hermeneutic-circle, audit-trail]
input: Research question, data corpus (interviews, field notes, documents, etc.), and analysis goals.
output: Themes/categories with supporting evidence, theoretical memos, and complete audit trail.
zetetic_gate:
  logical: "Coding must be systematic and documented — no impressionistic 'I felt that...'"
  critical: "Every theme must be grounded in data with traceable evidence chains"
  rational: "Approach must match the research question — do not default to thematic analysis"
  essential: "Maintain the audit trail — another researcher must be able to follow your reasoning"
composes: [research-question-formulation]
aliases: [qual-analysis, coding, thematic-analysis, grounded-theory]
hand_off:
  data_insufficient: "(stop) — insufficient data for the chosen approach; collect more or narrow scope"
  theory_emerging: "/verify-claim — test emerging theory against independent evidence"
  quantification_needed: "/mixed-methods-design — integrate with quantitative strand"
---

## Procedure

### Phase 1: Select Approach
1. Match the approach to the research question:
   - **Grounded theory (strauss)**: building theory from data. Use when no adequate theory exists.
   - **Thick description (geertz)**: deep contextual interpretation. Use when meaning-in-context is the goal.
   - **Discourse analysis (foucault)**: how language constructs power and knowledge. Use when examining institutional or systemic patterns.
   - **Hermeneutic interpretation (gadamer)**: understanding through dialogue between text and interpreter. Use when interpreting complex texts or historical material.
2. **Gate:** the approach must be justified by the question. If unclear, consult the research question formulation skill first.

### Phase 2: Apply Coding/Interpretation Method

#### If grounded theory (strauss):
3. Open coding: label phenomena in the data. Stay close to the data.
4. Axial coding: relate categories to subcategories. Identify conditions, actions, consequences.
5. Selective coding: identify the core category. Integrate around it.
6. Constant comparison throughout: each new code is compared to all existing codes.

#### If thick description (geertz):
3. Record the observed behavior in context.
4. Layer interpretations: what does it mean to the participants? What does it mean in the broader cultural context?
5. Distinguish thin description (what happened) from thick description (what it means).

#### If discourse analysis (foucault):
3. Identify the discursive formations: what can be said, by whom, under what conditions.
4. Map the power/knowledge relations embedded in the discourse.
5. Trace how the discourse constructs subjects, objects, and truths.

#### If hermeneutic interpretation (gadamer):
3. State your pre-understanding (prejudgments). Make the hermeneutic circle explicit.
4. Engage in dialogue with the text: question, interpret, revise understanding, repeat.
5. Document the fusion of horizons: where your understanding and the text's horizon meet.

### Phase 3: Generate Outputs (peirce)
7. peirce: generate theoretical memos — abductive insights that emerge during analysis.
8. Produce themes/categories with supporting evidence from the data.
9. **Gate:** every theme must have traceable evidence. "I felt that..." is not evidence.

### Phase 4: Audit Trail
10. Document every coding decision, category merge, and interpretive choice.
11. The audit trail must allow another researcher to follow the reasoning from raw data to findings.

## Output Format

```
## Qualitative Analysis: [research question]
### Approach: [grounded theory / thick description / discourse analysis / hermeneutic]
### Data corpus: [description]

### Themes/Categories:
| Theme | Definition | Supporting evidence | Data references |
|-------|-----------|-------------------|----------------|

### Theoretical memos (peirce):
| Memo | Insight | Grounded in |
|------|---------|------------|

### Audit trail summary:
| Decision | Rationale | Data that prompted it |
|----------|-----------|---------------------|
```
