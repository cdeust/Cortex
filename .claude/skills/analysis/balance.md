---
name: balance
description: >
  Conservation/mass-balance audit: enumerate all inputs and outputs of a conserved quantity,
  close the ledger, and investigate any residual.
category: analysis
trigger: >
  When money, data, requests, energy, time, or tokens are "disappearing"; when inputs
  and outputs haven't been verified to match; when a cost line is unexplained.
agents:
  - lavoisier
  - curie
shapes: [mass-balance, conservation-accounting, residual-as-discovery, sealed-system-experiment]
input: The system and the conserved quantity to audit.
output: Balance ledger with inputs, outputs, residual, and investigation of the residual if non-zero.
zetetic_gate:
  logical: "Inputs must equal outputs; residual is real data"
  critical: "Verify the quantity is actually conserved in this system"
  rational: "Seal the system if unmeasured flows are suspected"
  essential: "The residual IS the finding — do not dismiss it"
composes: []
aliases: [mass-balance, conservation-audit, reconcile]
hand_off:
  residual_found: "/isolate-signal — curie isolates the carrier"
  terminology_confusing: "lavoisier: rename to clarify"
---

## Procedure

1. **Identify the quantity.** What is conserved? (Money, records, requests, energy, tokens.) Verify it is actually conserved.
2. **Enumerate inputs.** Every flow into the system, with amounts.
3. **Enumerate outputs.** Every flow out, with amounts.
4. **Balance.** Sum inputs - sum outputs = residual.
5. **If residual ≠ 0:** The residual is a real entity. Name it. Seal the system (control all boundary flows). Re-measure. Then hand off to curie to isolate the carrier.
6. **If residual = 0:** The system balances. Document for future reference.

## Output Format

```
## Balance Audit: [system] — [conserved quantity]
| Inputs | Amount | | Outputs | Amount |
|--------|--------|-|---------|--------|
| Total in | [...] | | Total out | [...] |
| | | | **Residual** | **[...]** |
### Sealed? [yes — all flows measured / no — suspected unmeasured flows]
### Residual investigation: [if non-zero, what is the carrier?]
```
