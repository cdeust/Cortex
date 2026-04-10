---
name: migrate-db
description: >
  Database migration with schema validation, backward compatibility, and rollback plan.
category: engineering
trigger: >
  When a schema change is needed; when a migration must preserve data integrity;
  when backward compatibility with running code is required during deployment.
agents:
  - dba
  - engineer
  - lavoisier
shapes: [mass-balance, conservation-accounting]
input: The required schema change and the current schema.
output: Migration plan with SQL, validation queries, rollback script, and data-integrity verification.
zetetic_gate:
  logical: "Referential integrity preserved at every step"
  critical: "Data count before = data count after (lavoisier mass-balance)"
  rational: "Backward compatible with currently-deployed code"
  essential: "Minimum schema change to achieve the goal"
composes: [balance]
aliases: [migration, schema-change]
hand_off:
  complex_migration: "/deploy — devops deploys with blue-green strategy"
---

## Procedure

1. **dba designs migration.** Forward migration SQL + rollback SQL. Each step preserves referential integrity.
2. **lavoisier: mass-balance check.** Row counts, constraint counts, index counts before and after must balance. Any residual = lost data.
3. **Backward compatibility.** The new schema must work with the currently-deployed code AND the new code. If not, the migration needs a multi-step deployment plan.
4. **Test on staging.** Run the migration on a copy of production data. Verify mass-balance. Verify application behavior.
5. **Rollback test.** Run the rollback script. Verify the schema returns to its original state. Verify mass-balance.

## Output Format

```
## Migration Plan: [change description]

### Forward SQL: [...]
### Rollback SQL: [...]
### Mass-balance check:
| Metric | Before | After | Match? |
|--------|--------|-------|--------|
### Backward compatible: [yes/no — with which code version]
### Tested on staging: [yes/no]
### Rollback tested: [yes/no]
```
