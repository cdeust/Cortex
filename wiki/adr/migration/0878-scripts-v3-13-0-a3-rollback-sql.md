---
title: "ADR-0878 — scripts/v3_13_0_a3_rollback.sql rationale"
status: accepted
source: scripts/v3_13_0_a3_rollback.sql
---

# ADR-0878 — scripts/v3_13_0_a3_rollback.sql

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## scripts/v3_13_0_a3_rollback.sql — original line 20

````text
-- Note: any writes to homeostatic_state.factor since migration are lost
-- by design. The factor was never a source of truth — heat_base was.
-- ============================================================================
````
