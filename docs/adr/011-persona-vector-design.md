# ADR-011: 12-Dimensional Persona Vector Design

## Status
Accepted

## Context
The Felder-Silverman CognitiveStyle captures 3 numeric + 3 categorical dimensions. This is insufficient for fine-grained persona comparison, drift detection, and context steering. Anthropic's persona vector research shows that working style can be decomposed into interpretable directional components.

## Decision
Extend CognitiveStyle with 6 additional numeric dimensions derived from behavioral signals, yielding a 9-numeric-dimensional persona vector:

1. activeReflective (from CognitiveStyle)
2. sensingIntuitive (from CognitiveStyle)
3. sequentialGlobal (from CognitiveStyle)
4. thoroughness [-1 quick, +1 exhaustive] — from session duration + tool density
5. autonomy [-1 follows prompts, +1 proactive] — from Agent tool usage
6. verbosity [-1 terse, +1 detailed] — from message count signals
7. riskTolerance [-1 conservative, +1 bold] — from edit-to-read ratio
8. focusScope [-1 narrow, +1 broad] — from file spread signals
9. iterationSpeed [-1 deliberate, +1 rapid] — from burst ratio

Support cosine distance, drift detection (threshold 0.2), weighted composition (for global persona), and context steering (appending behavioral adjustment sentences).

## Consequences
- **Gain**: Fine-grained persona comparison across domains. Drift detection catches evolving work patterns. Context steering enables adaptive system prompts.
- **Gain**: All dimensions are interpretable with clear behavioral proxies, following Anthropic's emphasis on interpretability.
- **Lose**: Behavioral proxies are noisy (e.g., high Read ratio could mean unfamiliarity, not reflectiveness). EMA update (α=0.1) smooths this.
- **Neutral**: Backward compatible — existing CognitiveStyle dimensions are preserved as the first 3 persona dimensions.
