# Emotional Memory Research Synthesis

**Date:** 2026-04-06
**Status:** Research complete, implementation pending

## Three Research Streams

### 1. McGaugh/Yonelinas — Decay & Retrieval

| Finding | Value | Source |
|---|---|---|
| Effect size | g=0.38 (NOT 2-3x) | Yonelinas & Ritchey 2015, 165-study meta-analysis |
| Neutral decay rate | b=0.12/day | Yonelinas & Ritchey 2015 fitted model |
| Emotional decay rate | b=0.06/day | Yonelinas & Ritchey 2015 fitted model |
| Decay ratio | 2.0x (emotional decays at half the rate) | Yonelinas & Ritchey 2015 |
| Neutral asymptotic floor | c=0.35 | Yonelinas & Ritchey 2015 |
| Emotional asymptotic floor | c=0.42 (20% higher) | Yonelinas & Ritchey 2015 |
| Crossover timing | ~20-45 min (emotional worse initially) | Kleinsmith & Kaplan 1963 |
| Retrieval boost | phi_emot multiplier > 1.0 | Talmi, Lohnas & Daw 2019 (eCMR) |

**Time-dependent decay formula:**
```python
advantage(t) = arousal * 0.30 * (1 - exp(-t / 1.0))  # tau=1h, max_reduction=30%
decay_multiplier = 1.0 - advantage(t)  # applied to decay rate
```

**Retrieval boost formula:**
```python
boost = 1.0 + arousal * 0.15 * (1 - exp(-t / 1.0))  # 15% max from g=0.38
```

### 2. Bower — Mood-Congruent Retrieval

| Finding | Value | Source |
|---|---|---|
| Effect size | d=0.26 | Matt et al. 1992 meta-analysis |
| Probability boost | ~1.15x for congruent | Phillips et al. 2010 (r=0.13) |
| Positive MCM | More reliable | Eich 1995 |
| Negative MCM | Less reliable (mood repair) | Eich 1995 |
| Arousal interaction | Multiplicative | CMR3, Cohen & Kahana 2022 |

**Valence congruence formula:**
```python
valence_product = query_valence * memory_valence  # positive = congruent
base_effect = 0.13 * valence_product
arousal_factor = 1.0 + 0.5 * min(query_arousal, memory_arousal)
boost = clamp(1.0 + base_effect * arousal_factor, 0.85, 1.30)
```

**Integration:** Post-WRRF reranking signal, alpha=0.1-0.2. Small effect, not dominant.

### 3. Nader — Reconsolidation + Emotion

| Finding | Value | Source |
|---|---|---|
| PE gate | PE = mismatch * (1 - stability * 0.5) | Lee 2009 |
| theta_low | 0.15 | Osan-Tort-Amaral 2011 |
| theta_high | 0.65 | Osan-Tort-Amaral 2011 |
| Emotional multiplier | 1.0 + min(arousal, 0.8) | Yonelinas decay ratio |
| Labile window | 6h * (1 - 0.15 * arousal) | Nader 2000, Wang 2009 |
| Age factor | min(age_days/30, 1.0) * 0.15 | Milekic & Alberini 2002 |
| Strength gain | eta * PE * emotional_multiplier | Osan-Tort-Amaral 2011 |

**Current Cortex gaps:**
- Thresholds 0.3/0.7 (should be 0.15/0.65)
- No emotional modulation at all
- No PE gate with stability dampening
- No age-dependent threshold

## Implementation Priority

1. **Retrieval weighting** — Add emotional_valence to recall scoring (highest benchmark impact)
2. **Time-dependent decay** — Make emotional resistance grow with time, not flat
3. **Reconsolidation emotion boost** — Add emotional multiplier + fix thresholds
4. **Mood-congruence** — Post-WRRF reranking (smallest effect, implement last)

## Honest Uncertainties

- Osan-Tort-Amaral thresholds from binary attractor networks, not 384-dim embeddings
- No paper gives direct arousal-to-retrieval-score for IR systems
- tau=1h is adapted from 20-45min biological crossover
- 0.15 window compression coefficient is engineering approximation
- All constants need ablation validation on LongMemEval/LoCoMo/BEAM
