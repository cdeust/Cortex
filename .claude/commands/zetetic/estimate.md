# Quick Estimate

Fast Fermi bracket for a question. Produces an order-of-magnitude bound in under 2 minutes.

## Instructions

1. Take the question from $ARGUMENTS. If no units given, ask for units.

2. Decompose into 3-5 bracketable factors. State the source or reasoning for each bound.

3. Multiply to get the bracket [low, high].

4. Name the dominant uncertainty (the widest factor).

5. Cross-check with one independent decomposition. If they disagree by >10x, flag it.

6. Present:
   ```
   Quick Estimate: [question]
   Bracket: [low] to [high]
   Dominant uncertainty: [factor]
   Cross-check: [agrees/disagrees to x?]
   ```

7. Do NOT produce false precision. Brackets only.

$ARGUMENTS
