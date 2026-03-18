# ADR-006: Exponential Moving Average for Incremental Updates

## Status
Accepted

## Context
Need to update cognitive style dimensions after each session ends without performing a full profile rebuild. The update method must weight recent behavior while preserving historical stability — cognitive style does not change rapidly.

## Decision
Use Exponential Moving Average (EMA) with α=0.1 for numeric dimensions:

```
new_value = α × observed + (1 - α) × previous
```

For categorical dimensions (e.g., debugging style), use probabilistic adoption: the new value is adopted with probability α, otherwise the previous value is retained.

## Consequences
- **Gain**: O(1) update per dimension. History-weighted: 90% old state, 10% new observation. Naturally models cognitive style stability. No need to store full session history.
- **Lose**: Cannot recover historical data once merged. Early sessions have outsized influence until enough data accumulates. Fixed α may not suit all dimensions equally.
- **Neutral**: α=0.1 means ~10 sessions to shift a dimension significantly, which matches expected cognitive style drift rates.

## References
- Hunter, J.S. "The Exponentially Weighted Moving Average" (1986)
- NIST Engineering Statistics Handbook — Exponential Smoothing
