---
name: database-design-review
description: >
  Review database schema and data model: check normalization trade-offs (Alkhwarizmi),
  verify data conservation (Lavoisier), assess consistency guarantees (Lamport),
  and analyze scaling characteristics (Thompson).
category: architecture
trigger: >
  When a database schema is being designed or has evolved without review; when query
  performance is degrading and the schema may be the cause; when a migration is planned
  and the target schema needs validation; when data integrity issues surface.
agents:
  - lavoisier
  - lamport
  - thompson
  - alkhwarizmi
shapes: [data-conservation, consistency-model, scale-break, canonical-form]
input: Database schema (DDL, ORM models, or ER diagram), query patterns, and scale expectations.
output: Schema review report with findings per dimension and prioritized recommendations.
zetetic_gate:
  logical: "Every normalization/denormalization decision must have a stated justification"
  critical: "Review must be against actual query patterns, not hypothetical ones"
  rational: "Recommendations must balance correctness with practical performance needs"
  essential: "A schema that is perfectly normalized but cannot serve its queries has failed"
composes: [contract, adr]
aliases: [schema-review, data-model-review, db-review]
hand_off:
  migration_needed: "/migrate-system — plan the schema migration"
  consistency_decision: "/adr — document the consistency vs availability trade-off"
  scale_break_imminent: "/performance-investigation — investigate before it breaks"
---

## Procedure

### Phase 1: Canonical Form Analysis (alkhwarizmi)
1. alkhwarizmi: assess the normalization level. Is the schema in a justified normal form?
2. alkhwarizmi: for each denormalization, check that the justification is documented and valid (performance, query pattern, read/write ratio).
3. alkhwarizmi: identify redundant or derived data. Is there a single source of truth for each fact?
4. **Gate:** every deviation from canonical form must have a stated, verifiable justification.

### Phase 2: Data Conservation (lavoisier)
5. lavoisier: trace data flows. For each write path, verify that data is conserved — nothing silently dropped, truncated, or corrupted.
6. lavoisier: check integrity constraints. Are foreign keys, check constraints, and NOT NULL constraints aligned with the domain invariants?
7. **Gate:** if data can be lost silently through any write path, this is a critical finding.

### Phase 3: Consistency Model (lamport)
8. lamport: what consistency guarantees does the schema assume? (Strong, eventual, causal.)
9. lamport: are these guarantees actually provided by the database engine and configuration?
10. lamport: identify races. Are there concurrent write paths that could produce inconsistent state?
11. **Gate:** the assumed consistency model must match the actual consistency provided.

### Phase 4: Indexing and Query Alignment
12. Map the actual query patterns to the schema. For each frequent query, check:
    - Is there an appropriate index?
    - Does the query require a scan that could be avoided?
    - Are joins on indexed columns?
13. Identify missing indexes and over-indexing (write amplification from too many indexes).

### Phase 5: Scale Analysis (thompson)
14. thompson: at what scale does this schema break? (Row count, write throughput, query concurrency.)
15. thompson: what is the growth rate? When will the break point be reached?
16. thompson: what structural change would extend the scaling horizon?
17. **Gate:** scale-break must be quantified, not vague ("it might get slow").

## Output Format

```
## Database Design Review: [schema/system name]

### Normalization (alkhwarizmi):
| Table | Normal form | Denormalizations | Justification |
|-------|------------|-----------------|--------------|

### Data conservation (lavoisier):
| Write path | Data conserved? | Risk |
|-----------|----------------|------|

### Integrity constraints:
| Constraint | Present? | Aligned with domain? |
|-----------|---------|-------------------|

### Consistency (lamport):
Assumed: [...] | Actual: [...] | Match: [yes / no]
Race conditions: [...]

### Query alignment:
| Query pattern | Index? | Scan? | Recommendation |
|--------------|--------|-------|---------------|

### Scale analysis (thompson):
| Dimension | Current | Break point | Growth rate | Time to break |
|-----------|---------|------------|------------|--------------|

### Prioritized recommendations:
| # | Recommendation | Impact | Effort |
|---|---------------|--------|--------|
```
