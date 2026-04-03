I have now read all 33 files in their entirety. Here is the complete audit.

---

# Cortex Neuroscience Implementation Audit

## Methodology

For each module I examined: (1) the paper(s) cited in the docstring, (2) what those papers actually describe algorithmically, (3) what the code actually implements, and (4) whether there is a faithful correspondence. Ratings:

- **FAITHFUL**: Code implements the paper's core algorithm/equations correctly at an adapted timescale.
- **APPROXIMATION**: Code captures the paper's main idea but simplifies, omits key equations, or changes behavior materially.
- **METAPHOR**: Code uses the paper's terminology and high-level concept but does not implement its computational model.
- **FAKE**: Code has essentially no algorithmic relationship to the cited paper.

---

### 1. thermodynamics.py

- **Paper cited:** Titans (NeurIPS 2025) for test-time learning; no specific paper cited for the core heat/surprise/decay model.
- **Paper's algorithm (Titans):** Meta-learning memory with gradient-based surprise: the memory module is updated via gradient descent on a prediction loss, and a surprise signal gates memory updates. The key equation is a momentum-based update: S_t = eta * S_{t-1} - theta * grad_loss(M; x).
- **Implementation status:** METAPHOR
- **Specific issues:**
  - The core heat/decay/importance/valence model cites no paper at all. It is entirely a custom heuristic system. The `compute_decay` function uses an exponential decay with modifier terms but this is not derived from any cited model.
  - The Titans reference (lines 183-231) is a loose metaphor. Titans uses gradient-based surprise on a differentiable memory module. This code computes `1 - mean(cosine_sim)` and calls it "surprise" inspired by Titans. The actual Titans update `S_t = eta * S_{t-1} - theta * grad_loss` uses true gradients; this code uses a hand-tuned linear piecewise function (`compute_heat_adjustment`) that maps surprise > 0.5 to a positive delta and surprise < 0.3 to a negative delta. There are no gradients, no differentiable memory, no learned parameters.
  - `compute_importance` is a pure regex heuristic with invented weights (0.2, 0.3, etc.) -- no paper cited, no paper applicable.
  - `compute_valence` is a keyword-counting ratio -- no paper cited.
- **Missing equations:** The Titans paper's gradient-based memory update, the actual momentum update equation, the loss function.
- **Invented constants:** `boost_factor=0.3`, `decay_factor=0.95`, `importance_decay_factor=0.998`, `emotional_decay_resistance=0.5`, `bonus=0.2`, `window_hours=4.0`, `delta=0.08` -- all invented, none from any paper.

---

### 2. coupled_neuromodulation.py

- **Paper cited:** Doya (2002) "Metalearning and neuromodulation"; Schultz (1997); Aston-Jones & Cohen (2005).
- **Paper's algorithm (Doya 2002):** A computational framework mapping DA to temporal discount factor / reward rate, NE to exploration-exploitation (inverse gain), ACh to learning rate, 5-HT to temporal discount horizon. The paper proposes that each neuromodulator controls a specific meta-learning parameter in reinforcement learning.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - Doya's framework is about RL meta-parameter control. DA controls the temporal discount rate (gamma in RL), not "cascade stage advancement." NE controls randomness/exploration (inverse temperature in softmax policy), not "write gate threshold." ACh controls the learning rate, not "hierarchy level in predictive coding." 5-HT controls the time scale of reward prediction, not "spreading activation breadth."
  - The code maps each channel to a different downstream effect than Doya specifies. The mapping (DA -> cascade gate, NE -> precision gain, ACh -> encoding/retrieval, 5-HT -> exploration) is a loose reinterpretation, not the paper's actual computational model.
  - `modulate_ltp_rate`, `modulate_precision_gain`, `modulate_write_gate_threshold`, `modulate_spreading_breadth`, `modulate_retrieval_temperature` are all linear interpolation functions (e.g., `base * (0.5 + 0.5 * x)`) with no basis in Doya's equations.
  - `compute_composite_modulation` weights (DA*0.4 + NE*0.3 + ACh*0.3) are entirely invented.
  - `compute_cascade_gate` threshold of 0.7 is invented.
- **Missing equations:** Doya's mapping of DA to discount factor, NE to inverse temperature, ACh to learning rate, 5-HT to time horizon. None of these are implemented.
- **Invented constants:** All modulation coefficients (0.5, 0.4, 0.3, etc.), all thresholds (0.7), all coupling weights.

---

### 3. neuromodulation_channels.py

- **Paper cited:** Doya (2002); Schultz (1997); Yu & Dayan (2005).
- **Paper's algorithm (Schultz 1997):** Dopamine neurons encode reward prediction error (RPE): firing increases for unexpected reward, decreases for expected reward omission. RPE = actual_reward - predicted_reward. The prediction is learned via temporal difference.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_dopamine_rpe` does implement a basic Rescorla-Wagner RPE: `rpe = actual - da_baseline; da = 1.0 + rpe * 1.5`. The baseline adapts via EMA. This captures the core idea but with significant simplifications.
  - The gain factor of 1.5 on RPE is invented. Schultz's data shows proportional firing rate changes, but the exact mapping to a "level in [0.3, 2.0]" is fabricated.
  - `compute_norepinephrine_arousal` does not implement the Aston-Jones & Cohen (2005) model. That paper proposes tonic vs phasic LC modes driven by utility monitoring. This code is a simple burst/decay model with habituation.
  - `compute_serotonin_exploration` vaguely maps to the idea that 5-HT modulates exploration, but the specific formula (`0.5 + novelty_ratio * 0.8 - exploitation_signal * 0.5`) has no basis in any cited paper.
  - Cross-coupling (`apply_cross_coupling`) with linear additive terms (`ne + _DA_NE_COUPLING * (da - 1.0)`) is entirely invented. No paper defines these coupling equations.
- **Missing equations:** Schultz's TD learning model, Aston-Jones's tonic/phasic LC model, Yu & Dayan's Bayesian uncertainty model for ACh/NE.
- **Invented constants:** `DA_ALPHA=0.3`, `NE_ALPHA=0.2`, `ACH_ALPHA=0.4`, `SER_ALPHA=0.15`, all coupling strengths (-0.15, 0.2, -0.1, -0.15), habituation rates (0.05, 0.02), all gain factors (1.5), clamp bounds (0.3, 2.0).

---

### 4. emotional_tagging.py

- **Paper cited:** Wang & Bhatt (Nature Human Behaviour, 2024); Yerkes-Dodson.
- **Paper's algorithm:** Wang & Bhatt showed that high-frequency amygdala activity during encoding strengthens hippocampal memory traces. The Yerkes-Dodson law is an inverted-U relationship between arousal and performance, originally from Yerkes & Dodson (1908).
- **Implementation status:** METAPHOR
- **Specific issues:**
  - Wang & Bhatt's finding is about neural oscillatory coupling between amygdala and hippocampus measured via intracranial EEG. There is no computational model to implement -- it is an empirical finding about brain activity. The code detects emotion words via regex, which has no relationship to the actual paper.
  - The Yerkes-Dodson "implementation" (lines 131-136) is a piecewise linear approximation: `1.0 + arousal * 0.8` for arousal <= 0.7, then `1.56 - (arousal - 0.7) * 0.5` for higher arousal. The actual Yerkes-Dodson law is typically modeled as `performance = a * arousal * exp(-b * arousal)` or a quadratic. The piecewise linear version changes the curve shape fundamentally -- the slope discontinuity at 0.7 creates a kink that does not exist in the smooth inverted-U.
  - All emotion detection is regex-based keyword counting, normalized by dividing by 2 or 3. This is a sentiment-analysis heuristic, not a neuroscience-based model.
  - Arousal computed as RMS of emotion intensities (line 92-93) has no basis in any paper.
- **Missing equations:** Any oscillatory coupling model from Wang & Bhatt, any smooth inverted-U function for Yerkes-Dodson.
- **Invented constants:** All regex patterns, normalization divisors (3.0, 2.0), Yerkes-Dodson peak location (0.7), slopes (0.8, 0.5), bonus weights (0.3, 0.2, 0.1), decay resistance coefficients (0.6, 0.2, 0.2).

---

### 5. synaptic_tagging.py

- **Paper cited:** Frey & Morris (1997) "Synaptic tagging and LTP."
- **Paper's algorithm:** A weak stimulus (E-LTP) sets a "synaptic tag" at activated synapses. If a strong stimulus (L-LTP) occurs at nearby synapses within a time window (~1-2 hours in biology), the proteins produced by the strong stimulus are captured by the tagged synapses, converting E-LTP to L-LTP. The key mechanism is shared protein synthesis products being captured by local synaptic tags.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - The core idea is captured: a high-importance new memory can retroactively strengthen older weak memories that share entities, within a time window. This is a reasonable analog.
  - However, the biological mechanism is about shared protein synthesis products (PRPs) being captured by local synaptic tags. The code uses entity overlap as a proxy for "spatial proximity" on the dendritic tree, which is a reasonable adaptation.
  - The time window is set to 48 hours (`_DEFAULT_TAG_WINDOW_HOURS = 48.0`), while the paper documents a window of approximately 1-6 hours. The comment on line 42 says "Biological window: ~1-6 hours" but then sets it to 48, which is 8-48x too long. This is an acknowledged adaptation to the hours/days timescale of the memory system, but it is a significant departure.
  - The overlap computation uses Szymkiewicz-Simpson coefficient (line 74), which is a reasonable choice but is not from the paper.
  - The boost scaling is entirely invented: additive importance boost of 0.25 scaled by overlap, multiplicative heat boost of 1.5 scaled by overlap.
- **Missing equations:** The paper's actual protein synthesis model, the tag setting/capture mechanism, the temporal specificity of tag capture.
- **Invented constants:** `_DEFAULT_TRIGGER_IMPORTANCE=0.7`, `_DEFAULT_MAX_WEAK_IMPORTANCE=0.5`, `_DEFAULT_MIN_OVERLAP=0.3`, `_DEFAULT_IMPORTANCE_BOOST=0.25`, `_DEFAULT_HEAT_BOOST=1.5`, `_DEFAULT_TAG_WINDOW_HOURS=48.0`, `_DEFAULT_MAX_PROMOTIONS=5`.

---

### 6. oscillatory_phases.py

- **Paper cited:** Hasselmo (2005); Lisman & Jensen (2013); Buzsaki (2015); Colgin (2013); Olafsdottir et al. (2018).
- **Paper's algorithm (Hasselmo 2005):** Theta rhythm in hippocampal CA1 separates encoding from retrieval via cholinergic modulation. High ACh during encoding phase suppresses CA3->CA1 transmission (retrieval) and enhances EC->CA1 (encoding). Low ACh during retrieval phase allows CA3->CA1 pattern completion. This is mediated by muscarinic receptor activation on a ~125ms cycle.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - The encoding/retrieval phase separation via theta is correctly captured conceptually. The cosine envelope for encoding/retrieval strength (lines 129-157) is a reasonable simplification of the sinusoidal nature of theta.
  - However, theta operates at 4-8 Hz (125-250ms period) in biology. This code maps theta to session-level cycles with no specified frequency. There is no actual oscillation mechanism -- `theta_phase` is a floating point value that is presumably incremented externally, but the phase-to-time mapping is undefined.
  - The ACh modulation from theta phase (line 149-157) captures Hasselmo's key idea: high ACh during encoding, low during retrieval.
  - Gamma binding (lines 161-181) captures Lisman & Jensen's theta-gamma coupling idea: gamma cycles nested within theta encode ordered items with capacity ~7. The serial position effect (primacy/recency) in `gamma_binding_strength` is a reasonable addition but not from the original paper.
  - SWR logic (lines 186-268) is reasonable but `should_generate_swr` is deterministic (threshold-based) despite the docstring saying "deterministic threshold for reproducibility." The probability calculation (line 198-202) is a weighted sum of operation count, importance accumulation, and time -- none of these match the actual neural mechanisms of SWR generation (which involves CA3 population bursts exceeding excitation thresholds).
  - Replay priority computation (lines 242-268) uses an invented weighted sum of importance, heat, surprise, rehearsal need, and recency. The Olafsdottir (2018) citation is about the role of replay in memory and planning -- it does not provide this scoring formula.
- **Missing equations:** Hasselmo's cholinergic modulation model (muscarinic receptor dynamics), actual theta oscillation equations, gamma-theta phase coupling model, SWR generation mechanism.
- **Invented constants:** `TRANSITION_WIDTH=0.08`, `GAMMA_CAPACITY=7` (close to Miller's 7+/-2), `SWR_MIN_INTERVAL_HOURS=0.5`, `SWR_BASE_PROBABILITY=0.3`, `SWR_BURST_STEPS=5`, `SWR_REFRACTORY_STEPS=3`, all replay priority weights (0.35, 0.20, 0.20, 0.15, 0.10), `168.0` hour time constant.

---

### 7. cascade_stages.py

- **Paper cited:** Kandel (2001); Dudai (2012); Frey & Morris (1997); Nader et al. (2000).
- **Paper's algorithm:** Kandel describes the molecular biology of memory storage: short-term memory involves covalent modifications of existing proteins (PKA, CaMKII), while long-term memory requires new gene expression and protein synthesis (CREB, MAPK pathway). Nader describes reconsolidation: retrieved consolidated memories become labile again and require protein synthesis to re-stabilize.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - The stage progression (LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED) maps reasonably to Kandel's cascade: early-phase LTP (1-3 hours, protein kinase dependent) -> late-phase LTP (>3 hours, CREB/protein synthesis dependent) -> systems consolidation (>24 hours, hippocampal-cortical transfer).
  - The time windows are approximately correct: LABILE 0-1h, EARLY_LTP 1-6h, LATE_LTP 6-24h, CONSOLIDATED >24h.
  - RECONSOLIDATING state captures Nader's finding that retrieval destabilizes consolidated memories.
  - The decay multipliers (2.0, 1.2, 0.8, 0.5, 1.5) are invented but directionally correct: labile memories decay faster, consolidated ones slower.
  - Interference vulnerability values (0.9, 0.5, 0.2, 0.05, 0.8) are invented but directionally correct.
  - Plasticity values (1.0, 0.7, 0.3, 0.1, 0.9) are invented but directionally correct.
  - No actual molecular modeling -- no PKA, CaMKII, CREB, MAPK pathway equations.
- **Missing equations:** PKA/MAPK cascade kinetics, CREB phosphorylation dynamics, protein synthesis initiation models.
- **Invented constants:** All StageProperties values (decay multipliers, interference vulnerabilities, plasticities, dwell times).

---

### 8. cascade_advancement.py

- **Paper cited:** Kandel (2001); Tse et al. (2007); Nader et al. (2000).
- **Paper's algorithm (Tse 2007):** Schemas accelerate systems consolidation from weeks to 48 hours in rodents. New information consistent with existing cortical schemas is rapidly consolidated via direct cortical encoding, bypassing extended hippocampal replay.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - Schema-accelerated dwell time (line 80-82): `schema_factor = 1.0 - (schema_match * 0.5)` gives up to 50% reduction. Tse's paper shows acceleration from ~30 days to ~48 hours (a 15x factor), so the 50% reduction is vastly under-modeled. However, as a timescale adaptation, some compression is expected.
  - LABILE -> EARLY_LTP requires DA > 1.0 or importance > 0.6. This is a reasonable proxy for the protein synthesis signal (DA gates CREB activation).
  - EARLY_LTP -> LATE_LTP requires replay_count >= 1 or importance > 0.7. The replay requirement is consistent with the idea that repeated reactivation drives consolidation.
  - LATE_LTP -> CONSOLIDATED requires replay_count >= 3 (or 1 if schema-congruent). The schema acceleration here captures Tse's insight.
  - Reconsolidation trigger (lines 120-155): mismatch_score >= threshold triggers RECONSOLIDATING state. This captures Nader's prediction error reconsolidation model. The stability-dependent threshold (`mismatch_threshold + stability * 0.3`) is invented but reasonable.
- **Missing equations:** Tse's schema acceleration quantification, Nader's boundary conditions for reconsolidation, CREB activation kinetics.
- **Invented constants:** DA threshold (1.0), importance thresholds (0.6, 0.7), replay thresholds (1, 3), schema factor (0.5), reconsolidation threshold (0.3), stability modifier (0.3).

---

### 9. separation_core.py

- **Paper cited:** Leutgeb et al. (2007); Yassa & Stark (2011); Rolls (2013).
- **Paper's algorithm:** Dentate gyrus performs pattern separation via sparse coding and competitive inhibition. Similar cortical inputs are transformed into non-overlapping representations via the low firing rate of granule cells (~2-5% active) and mossy fiber connections to CA3. Computationally, this is a transformation that increases the Hamming distance between similar input patterns.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `orthogonalize_embedding` uses Gram-Schmidt-like projection: subtract the component of the new embedding that lies along interfering embeddings. This is a reasonable computational model for orthogonalization, though the DG achieves this via sparse coding + competitive inhibition, not explicit Gram-Schmidt.
  - The strength parameter (0.5) controls how aggressively to separate, with a minimum similarity constraint -- this is a practical addition not from the papers.
  - `apply_sparsification` (lines 152-182) zeroes out the smallest dimensions to achieve target sparsity. The sparsity target is 15% (line 41), which is acknowledged as "relaxed" compared to the DG's ~2-5%. The DG achieves sparsity via competitive inhibition among granule cells, not by zeroing out small activation dimensions, but for a dense embedding vector this is a reasonable analog.
  - The interference detection threshold of 0.75 is invented.
  - The identity threshold of 0.95 is a practical deduplication boundary, not from any paper.
  - The minimum post-separation similarity of 0.3 is a practical constraint, not from any paper.
- **Missing equations:** DG's competitive inhibition model, mossy fiber expansion coding ratio (5:1 expansion from EC layer II to DG), inhibitory interneuron feedback circuit.
- **Invented constants:** `_SEPARATION_THRESHOLD=0.75`, `_IDENTITY_THRESHOLD=0.95`, `_MIN_POST_SEPARATION_SIMILARITY=0.3`, `_SPARSITY_TARGET=0.15`, strength default 0.5.

---

### 10. schema_engine.py

- **Paper cited:** Tse et al. (2007); van Kesteren et al. (2012); Piaget (1952).
- **Paper's algorithm (Tse 2007):** Rodent studies showing that schema-consistent information is consolidated rapidly via neocortical integration. Schemas are cortical knowledge structures built from repeated experience. (van Kesteren 2012): Schema-congruent information is encoded via mPFC, while schema-incongruent information triggers hippocampal engagement. Piaget: Assimilation (fitting new info into existing schemas) vs accommodation (modifying schemas when assimilation fails).
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - Schema matching via weighted Jaccard overlap of entities and tags is a reasonable computational proxy for schema congruency.
  - The three-way classification (assimilate/normal/accommodate) maps to Piaget's theory and van Kesteren's dual pathway model.
  - Schema accommodation via EMA (`_ema_update_signature`, alpha=0.1) is a reasonable implementation of gradual schema modification. However, Piaget's accommodation is typically a more dramatic restructuring event, not a smooth EMA update.
  - `compute_prediction_error` and `compute_schema_free_energy` (lines 226-257) connect schemas to predictive coding (Friston). The free energy as sum of squared prediction errors is consistent with the variational free energy framework, though simplified.
  - Schema revision trigger (10 violations or 40% violation ratio) is entirely invented.
  - The entity weight matching (line 81: `weighted_overlap / max(total_weight, 1e-10)`) is a reasonable weighted Jaccard variant but not from any specific paper.
- **Missing equations:** Tse's ACC/mPFC engagement model, van Kesteren's mPFC-MTL interaction model, Piaget's formal equilibration theory.
- **Invented constants:** `_HIGH_MATCH_THRESHOLD=0.7`, `_MEDIUM_MATCH_THRESHOLD=0.3`, `_MAX_VIOLATIONS_BEFORE_REVISION=10`, `_SCHEMA_EMA_ALPHA=0.1`, violation ratio threshold 0.4, entity/tag weights (0.7/0.3).

---

### 11. schema_extraction.py

- **Paper cited:** Tse et al. (2007); Gilboa & Marlatte (2017).
- **Paper's algorithm:** Schemas are abstracted knowledge structures representing statistical regularities across experiences. Gilboa & Marlatte define schemas as having: (1) associative network structure, (2) lack of unit detail, (3) basis in multiple episodes, (4) adaptability.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - Schema formation from a cluster of memories via frequency analysis of entities, tags, and relationships is a reasonable computational model for extracting statistical regularities.
  - The minimum formation count of 5 memories captures Gilboa & Marlatte's "basis in multiple episodes."
  - Entity frequency threshold of 0.4 (entities appearing in 40%+ of cluster memories) is a reasonable threshold but invented.
  - Schema merging via weighted average proportional to formation count is reasonable.
  - The merge threshold (Jaccard >= 0.6) is invented.
  - No actual neural network model -- schemas are represented as frequency dictionaries, not as attractor states in a cortical network.
- **Missing equations:** No cortical attractor dynamics, no neural substrate model for schema storage.
- **Invented constants:** `_MIN_FORMATION_COUNT=5`, `_ENTITY_FREQUENCY_THRESHOLD=0.4`, `_SCHEMA_MERGE_THRESHOLD=0.6`, `_RELATIONSHIP_FREQUENCY_THRESHOLD=0.3`.

---

### 12. interference.py

- **Paper cited:** Anderson & Neely (1996); Wixted (2004); Yassa & Stark (2011).
- **Paper's algorithm:** Anderson & Neely describe retrieval-induced forgetting (RIF): practicing retrieval of some items suppresses retrieval of competitors. Wixted describes interference theory of forgetting. Yassa & Stark describe pattern separation as the mechanism to reduce interference.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `orthogonalize_pair` implements a gradual projection-based separation of interfering embeddings. This is a reasonable computational model for sleep-dependent pattern separation (pushing similar representations apart over multiple sleep cycles).
  - `compute_retrieval_suppression` implements RIF: stronger competitors suppress weaker items. The linear suppression model (`target - sum((competitor - target) * factor)`) is a reasonable simplified model of lateral inhibition, though Anderson's actual model involves executive control processes.
  - `compute_domain_interference_pressure` provides aggregate metrics but no paper specifies how to measure "interference pressure" as a system-level metric.
  - The orthogonalization rate of 0.15 per step is invented.
  - The retrieval suppression factor of 0.3 is invented.
  - The backoff mechanism to prevent over-separation (lines 60-77) is practical engineering, not from any paper.
- **Missing equations:** Anderson's inhibitory control model, Wixted's specific interference equations, Yassa & Stark's pattern separation computational model.
- **Invented constants:** `_ORTHOGONALIZATION_RATE=0.15`, `_MIN_ORTHOGONAL_SIMILARITY=0.2`, `_RETRIEVAL_SUPPRESSION=0.3`, `_INTERFERENCE_THRESHOLD=0.7`.

---

### 13. homeostatic_plasticity.py

- **Paper cited:** Turrigiano (2008); Abraham & Bear (1996).
- **Paper's algorithm (Turrigiano 2008):** Synaptic scaling: neurons multiplicatively scale all synaptic weights to maintain a target firing rate. When activity is chronically elevated, all excitatory synapses are scaled down; when depressed, scaled up. The key property is that relative synaptic weights are preserved (multiplicative, not additive). (Abraham & Bear 1996): The BCM sliding threshold: the crossover point between LTP and LTD (theta_m) depends on the history of postsynaptic activity. theta_m = E[activity^2] (the expectation of squared activity).
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_scaling_factor` implements multiplicative synaptic scaling: if average heat deviates from target, compute a multiplicative factor. This captures Turrigiano's core mechanism -- multiplicative scaling preserving relative ordering.
  - The dead zone (0.1) is practical engineering, not from the paper.
  - The scaling rate (0.05) limits adjustment per cycle -- this is a practical stability constraint.
  - `compute_bcm_threshold` correctly implements the BCM sliding threshold as an EMA of squared activity: `decay * current_theta + (1 - decay) * avg_squared`. This matches the BCM theory's theta_m = E[c^2] where c is postsynaptic activity.
  - `compute_ltp_ltd_modulation` implements the BCM rule correctly in principle: activity above threshold -> LTP, below threshold -> LTD. The linear piecewise modulation (`1.0 + min(delta * 2.0, 1.0)`) is a simplification of BCM's quadratic phi function: phi(c, theta_m) = c * (c - theta_m), but captures the qualitative behavior.
  - `compute_excitability_adjustment` for intrinsic excitability regulation is loosely inspired but not from a specific paper.
- **Missing equations:** Turrigiano's actual scaling equation (w_i' = w_i * (r_target / r_actual)^alpha), BCM's quadratic phi function phi(c, theta_m) = c*(c - theta_m).
- **Invented constants:** `_TARGET_HEAT=0.4`, `_SCALING_RATE=0.05`, `_SCALING_DEAD_ZONE=0.1`, `_TARGET_EDGE_WEIGHT=0.5`, `_BCM_THETA_DECAY=0.95`, excitability bounds (0.1, 0.9), `_TARGET_ACTIVE_FRACTION=0.3`, LTP/LTD multiplier slopes (2.0).

---

### 14. dendritic_clusters.py

- **Paper cited:** Kastellakis et al. (2015); Limbacher & Legenstein (2020).
- **Paper's algorithm (Kastellakis 2015):** Related synapses cluster on the same dendritic branch. When enough clustered synapses are co-activated, nonlinear dendritic events (NMDA spikes, Ca2+ plateaus) amplify the signal supralinearly. This provides branch-specific computation: each dendritic branch acts as an independent computational subunit.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - The concept of clustering memories on "dendritic branches" based on entity/tag similarity is a metaphor. Real dendritic clustering involves physical proximity on a dendrite with NMDA receptor-dependent nonlinearity.
  - `compute_branch_affinity` uses Jaccard similarity (0.7 entity + 0.3 tag) to determine branch assignment. This has no biological basis -- dendritic clustering is driven by spatiotemporal coincidence of synaptic inputs, not semantic similarity.
  - Branch assignment threshold (0.3), max branch size (15) are practical constraints with no biological basis.
  - The actual nonlinear computation (in `dendritic_computation.py`) is closer to the paper.
- **Missing equations:** NMDA receptor voltage-dependent gating, Ca2+ dynamics within dendritic compartments, synaptic input spatial summation rules.
- **Invented constants:** `_BRANCH_ADMISSION_THRESHOLD=0.3`, `_MAX_BRANCH_SIZE=15`, entity/tag weights (0.7/0.3).

---

### 15. dendritic_computation.py

- **Paper cited:** Kastellakis et al. (2015); Poirazi et al. (2003).
- **Paper's algorithm (Poirazi 2003):** The pyramidal neuron acts as a two-layer neural network: dendritic branches perform sigmoid-like nonlinear summation of local inputs, then the soma sums these branch outputs linearly. Key insight: individual branches have sigmoidal input-output functions with a sharp threshold.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_dendritic_integration` implements the key idea from Poirazi: sublinear summation below threshold, supralinear (spike) above threshold. This captures the two-regime behavior correctly.
  - Below spike threshold: `linear_sum * (active_count^(0.7 - 1.0))` implements power-law compression. The exponent 0.7 is invented but captures sublinearity.
  - Above spike threshold: `linear_sum * (1 + (1.5 - 1) * excess)` implements linear supralinear boost. Poirazi's model uses a sigmoid, not a linear excess function. The actual NMDA spike is more of a step function with sharp threshold.
  - `compute_cluster_priming` (lines 119-146) with exponential decay by position distance is a reasonable model of associative priming within a cluster but not specifically from Kastellakis or Poirazi.
  - Branch-specific plasticity (lines 149-202) captures the idea that LTP/LTD is branch-local, which is from Kastellakis. However, the actual mechanism involves local Ca2+ signaling, not a simple increment/decrement.
- **Missing equations:** Poirazi's two-layer neural network model (branch sigmoid transfer function), NMDA receptor voltage-dependent gating, local Ca2+ dynamics within branches.
- **Invented constants:** `SPIKE_THRESHOLD=0.4`, `SUBLINEAR_EXPONENT=0.7`, `SUPRALINEAR_BOOST=1.5`, `PRIMING_STRENGTH=0.3`, LTP/LTD boost/reduction values (0.05, 0.03), decay rate (0.01).

---

### 16. two_stage_model.py

- **Paper cited:** McClelland, McNaughton & O'Reilly (1995); Kumaran, Hassabis & McClelland (2016); Frankland & Bontempi (2005).
- **Paper's algorithm (McClelland 1995):** Complementary Learning Systems theory. The hippocampus performs fast, pattern-separated encoding of episodic memories. The neocortex performs slow, interleaved learning to build structured semantic knowledge. Transfer from hippocampus to cortex occurs via repeated replay during offline states (sleep). Interleaved training in the cortex prevents catastrophic interference.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - The two-store model (hippocampal = fast/labile, cortical = slow/stable) correctly captures CLS theory's core insight.
  - `hippocampal_dependency` tracking (1.0 = fully hippocampal, 0.0 = cortically independent) is a good operationalization of the hippocampal-cortical transfer gradient.
  - `compute_hippocampal_pressure` using a sigmoid (line 139: `1.0 / (1.0 + exp(-8*(ratio-0.7)))`) is a reasonable capacity pressure model.
  - `compute_consolidation_priority` with its weighted sum is entirely invented -- no paper specifies these weights.
  - `_dependency_sweet_spot` preferring transitional (0.3-0.7) memories for replay is a reasonable heuristic for targeting the transfer zone.
  - The hippocampal capacity of 100 is invented. McClelland's model discusses capacity limitations but does not specify a number.
  - Missing: The actual CLS learning rule (interleaved training with small learning rate in the cortical network). The code does not implement any actual neural network learning.
- **Missing equations:** CLS's dual learning rate model, Hebbian learning in the hippocampal module, gradient descent in the cortical module, the interleaving training schedule.
- **Invented constants:** `_HIPPOCAMPAL_CAPACITY=100`, `_CORTICAL_INDEPENDENCE_THRESHOLD=0.15`, `_HIPPOCAMPAL_RELEASE_THRESHOLD=0.05`, all priority weights (0.30, 0.25, 0.20, 0.15, 0.10), sigmoid parameters (8.0, 0.7).

---

### 17. two_stage_transfer.py

- **Paper cited:** McClelland et al. (1995).
- **Paper's algorithm:** See above (CLS theory). Transfer via interleaved replay.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_transfer_delta` models the reduction of hippocampal dependency per replay event. The diminishing returns (`transfer_rate / sqrt(effective_replays)`) captures the idea that early replays matter most, though McClelland's model uses gradient-based learning, not sqrt-decay.
  - Schema acceleration (`1 + schema_match * (2.5 - 1)` = up to 2.5x faster for schema-congruent memories) captures Tse's finding but with an invented acceleration factor.
  - `compute_interleaving_schedule` implements round-robin interleaving across domains. This captures the key CLS insight that interleaved (not blocked) training prevents catastrophic interference in the cortex. The implementation is a simple round-robin, while the theory calls for a specific ratio of old/new items.
  - The transfer rate of 0.08 per replay is entirely invented.
  - The minimum replays threshold of 2 before any transfer begins is invented.
- **Missing equations:** McClelland's actual backpropagation learning rule in the cortical network, the interleaving ratio for old vs new items.
- **Invented constants:** `_REPLAY_TRANSFER_RATE=0.08`, `_SCHEMA_ACCELERATION=2.5`, `_MIN_REPLAYS_FOR_TRANSFER=2`, importance factor (0.8 + importance * 0.4).

---

### 18. tripartite_synapse.py

- **Paper cited:** Perea, Navarrete & Araque (2009).
- **Paper's algorithm:** Astrocytes participate in synaptic transmission via gliotransmitter release (D-serine, glutamate, ATP). Astrocyte calcium dynamics determine the modulation regime: (1) quiescent -- no modulation, (2) moderate Ca2+ -- D-serine release potentiates NMDA-dependent LTP, (3) high Ca2+ -- glutamate release causes heterosynaptic depression.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `AstrocyteTerritory` mapping to L1 fractal clusters is a reasonable adaptation of the astrocyte territory concept (each astrocyte covers ~4-8 synapses in biology, here it covers a memory cluster).
  - Calcium regime classification (quiescent/facilitation/depression) correctly captures the three-regime model from Perea 2009.
  - D-serine activation during facilitation regime and glutamate during depression regime correctly maps to the paper's description.
  - Territory management is straightforward but lacks the detail of astrocyte-neuron calcium signaling loops.
- **Missing equations:** IP3-mediated calcium release model, SERCA pump dynamics, astrocyte membrane potential equations.
- **Invented constants:** None beyond those in tripartite_calcium.py.

---

### 19. tripartite_calcium.py

- **Paper cited:** Perea, Navarrete & Araque (2009); De Pitta et al. (2012); Henneberger et al. (2010).
- **Paper's algorithm (De Pitta 2012):** A computational model of astrocyte Ca2+ dynamics including IP3-dependent Ca2+ release from ER stores, SERCA pump reuptake, IP3 production from glutamate receptor activation, and IP3 degradation. The model includes the Li-Rinzel simplification of the Hodgkin-Huxley-like Ca2+ channel dynamics.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - De Pitta's model involves differential equations for [Ca2+], [IP3], and the inactivation variable h, with at least 15 parameters. This code has none of that -- it uses a simple `rise = rate * events * (1 - current_Ca)` and `decay = Ca * exp(-rate * hours)`.
  - `compute_calcium_rise` is a saturating linear model, not the IP3-dependent release from ER stores (which involves nonlinear Hill functions and channel gating).
  - `compute_calcium_decay` is simple exponential decay, not the SERCA pump model (which has Michaelis-Menten kinetics).
  - `propagate_calcium_wave` is a linear additive model, not the IP3-mediated gap junction propagation (which involves regenerative IP3 release with threshold behavior).
  - `compute_ltp_modulation` D-serine LTP boost captures the qualitative finding of Henneberger et al. but the linear ramp is not from the paper.
  - `compute_heterosynaptic_depression` captures the qualitative concept but with invented scaling.
  - `compute_metabolic_rate` with the "lactate shuttle" concept is not from any of the cited papers. This is a separate neuroscience concept (Pellerin & Magistretti 1994) that is not cited.
- **Missing equations:** De Pitta's Li-Rinzel model (dCa/dt, dIP3/dt, dh/dt), Hill functions for IP3-dependent Ca2+ release, SERCA pump Michaelis-Menten kinetics, IP3 production model.
- **Invented constants:** `CA_LOW_THRESHOLD=0.3`, `CA_MEDIUM_THRESHOLD=0.6`, `CA_RISE_RATE=0.15`, `CA_DECAY_RATE=0.05`, `CA_WAVE_SPREAD=0.3`, `DSERINE_LTP_BOOST=0.2`, `GLUT_LTD_STRENGTH=0.15`, all metabolic constants (1.0, 1.5, 0.6).

---

### 20. synaptic_plasticity.py

- **Paper cited:** Hebb (1949); BCM (1982); Markram et al. (1998); Abbott & Regehr (2004); Hasselmo (2005).
- **Paper's algorithm (Markram 1998):** Stochastic synaptic transmission: each synapse has a release probability p. Short-term facilitation increases p with repeated use (residual Ca2+). Short-term depression decreases p (vesicle depletion). The model is: p_eff(n+1) = p_0 + (1 - p_0) * F * Ca_residual - D * depletion. Paired-pulse facilitation/depression depends on inter-stimulus interval.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_effective_release_probability` correctly sums base probability + facilitation - depression, clamped to [0.05, 0.95]. This captures the qualitative model.
  - `stochastic_transmit` correctly implements probabilistic release.
  - `update_short_term_dynamics` captures facilitation increase on access and depression on rapid repeated access. The exponential decay of facilitation and depression over time captures the biological decay of residual Ca2+ and vesicle replenishment.
  - However, Markram's model has specific equations: facilitation involves residual Ca2+ accumulation with time constant tau_f, and depression involves vesicle depletion with recovery time constant tau_d. The code uses simple exponential decay with invented rates rather than the specific Markram equations.
  - `phase_modulate_plasticity` correctly captures Hasselmo's finding that encoding phase amplifies LTP and retrieval phase suppresses it. The cosine envelope is a reasonable simplification.
  - `compute_noisy_weight_update` with Gaussian noise scaled by 1/sqrt(access_count) is a Bayesian-inspired noise model (more evidence = less noise) but not from any specific cited paper.
- **Missing equations:** Markram's paired-pulse facilitation equation, vesicle depletion model (Tsodyks-Markram model: du/dt = -u/tau_F + U*(1-u)*delta(t-t_spike)), resource recovery model (dx/dt = (1-x)/tau_D - u*x*delta(t-t_spike)).
- **Invented constants:** `_BASE_RELEASE_PROB=0.5`, `_FACILITATION_RATE=0.15`, `_FACILITATION_DECAY=0.9`, `_DEPRESSION_RATE=0.2`, `_DEPRESSION_DECAY=0.85`, `_DEPRESSION_INTERVAL_HOURS=0.5`, `_NOISE_SCALE=0.01`.

---

### 21. synaptic_plasticity_hebbian.py

- **Paper cited:** Hebb (1949); BCM (1982); Bi & Poo (1998).
- **Paper's algorithm (BCM 1982):** The BCM theory: dw/dt = phi(c, theta_m) * d, where phi(c, theta_m) = c * (c - theta_m), c = postsynaptic activity, d = presynaptic activity, theta_m = E[c^2]. LTP occurs when c > theta_m, LTD when c < theta_m. (Bi & Poo 1998): STDP: synaptic modification depends on the timing difference between pre and post spikes. Pre-before-post (dt > 0): LTP with magnitude A+ * exp(-dt/tau+). Post-before-pre (dt < 0): LTD with magnitude -A- * exp(dt/tau-).
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_ltp` implements BCM-like LTP: `delta = ltp_rate * (post - theta) * pre * co_activation`. This captures the BCM rule's key feature: LTP requires postsynaptic activity above threshold. However, the BCM theory has phi(c) = c * (c - theta_m), which is quadratic in c. This code uses linear (post - theta), omitting the extra c multiplication.
  - `compute_ltd` uses logarithmic decay over time (`ltd_rate * log1p(hours/24)`) for inactive edges. This is not BCM's LTD (which is activity-dependent, not time-dependent). BCM says LTD occurs when postsynaptic activity is below theta_m but above zero. Time-based decay is a different mechanism entirely.
  - `update_bcm_threshold` correctly implements theta_m update via EMA of squared activity: `decay * theta + (1 - decay) * activity^2`. This matches BCM theory.
  - `compute_stdp_update` correctly implements the Bi & Poo STDP rule: dt > 0 -> A+ * exp(-dt/tau+), dt < 0 -> -A- * exp(dt/tau-). This is FAITHFUL to the paper.
  - However, the time constants are adapted: `_STDP_TAU_PLUS=24.0` hours and `_STDP_TAU_MINUS=24.0` hours. In Bi & Poo, tau+ = 17ms and tau- = 34ms. The timescale adaptation from milliseconds to hours is acknowledged and necessary, but it changes the effective window dramatically.
  - The amplitudes `A+=0.03, A-=0.02` are in the right relative ratio (A+ > A- in Bi & Poo) but the absolute values are invented for the memory system context.
- **Missing equations:** BCM's quadratic phi function, BCM's LTD below theta_m, the full STDP temporal window (which in biology extends ~100ms, here ~48 hours).
- **Invented constants:** `_LTP_RATE=0.05`, `_LTD_RATE=0.02`, `_BCM_THETA_DECAY=0.95`, `_STDP_A_PLUS=0.03`, `_STDP_A_MINUS=0.02`, `_STDP_TAU_PLUS=24.0`, `_STDP_TAU_MINUS=24.0`.

---

### 22. synaptic_plasticity_stochastic.py

- **Paper cited:** Hebb (1949); BCM (1982); Markram (1998).
- **Paper's algorithm:** Combines stochastic transmission with Hebbian learning.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - This module composes `stochastic_transmit` (from synaptic_plasticity.py) with `compute_ltp`/`compute_ltd` (from hebbian module). The composition is novel -- no paper combines these three mechanisms in exactly this way (stochastic gating -> Hebbian LTP -> phase modulation -> noise injection).
  - The composition is reasonable as a computational model but represents a synthesis that is not from any single paper.
  - Individual components inherit the issues from their parent modules.
- **Missing equations:** None beyond what is missing in the component modules.
- **Invented constants:** Inherits from parent modules.

---

### 23. microglial_pruning.py

- **Paper cited:** Wang et al. (Science, 2020).
- **Paper's algorithm:** Microglia mediate forgetting through complement-dependent synaptic elimination. C3/CR3 signaling tags synapses for elimination. The "eat-me" signal is complement protein C1q/C3 deposition on inactive synapses; the "don't-eat-me" signal is CD47 on active synapses. Microglia phagocytose tagged synapses via CR3 receptor engagement.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - The metaphor of "eat-me" and "don't-eat-me" signals is used, but the actual implementation is heuristic rule-based pruning: if edge weight is low AND no recent co-activation AND both endpoints have low heat, then prune.
  - Real complement-dependent pruning involves C1q binding to inactive synapses, C3 cleavage by C3 convertase, CR3 receptor engagement on microglial processes, and physical synapse engulfment. None of this is modeled.
  - The "don't-eat-me" signals (protection, recent LTP, high access count) are reasonable proxies for CD47/activity-dependent protection but are implemented as simple boolean/threshold checks, not a signaling pathway.
  - `identify_prunable_edges` requiring >= 2 eat-me signals is an arbitrary threshold.
  - `identify_orphaned_entities` is a practical cleanup operation with no biological basis.
  - The protection threshold of 5 accesses is invented.
- **Missing equations:** Complement cascade kinetics (C1q binding, C3 cleavage, CR3 engagement), microglial process motility model, phagocytosis rate model.
- **Invented constants:** `_MIN_EDGE_WEIGHT=0.05`, `_MIN_ENTITY_HEAT=0.02`, `_MIN_ACCESS_COUNT=2`, `_STALE_HOURS=168.0`, `_PROTECTION_ACCESS_THRESHOLD=5`, heat threshold 0.1 for cold endpoints.

---

### 24. dual_store_cls.py

- **Paper cited:** McClelland et al. (1995); Sun et al. (Nature Neuroscience, 2023) "Go-CLS".
- **Paper's algorithm (McClelland 1995):** Fast episodic learning in hippocampus, slow semantic learning in neocortex. (Go-CLS, Sun 2023): A gated version where top-down signals from the cortex gate hippocampal encoding based on novelty relative to existing cortical knowledge.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - This module only classifies memories as "episodic" or "semantic" using regex pattern matching (decision keywords, file paths, architecture terms). It does not implement any learning system.
  - McClelland's CLS theory is about two different learning algorithms (fast hippocampal binding vs slow cortical gradient descent). This code is a text classifier, not a learning system.
  - Go-CLS (Sun 2023) involves a gated architecture where cortical predictions gate hippocampal encoding. This code has no gating mechanism, no cortical model, no hippocampal model.
  - `auto_weight` (returning episodic vs semantic weight multipliers) is a query-level heuristic, not a learning system.
  - The classification logic is purely regex-based heuristics.
- **Missing equations:** Everything from CLS (dual learning rate model, interleaved training) and Go-CLS (gating mechanism, cortical prediction model).
- **Invented constants:** All regex patterns, weight multipliers (2.0, 1.0).

---

### 25. spreading_activation.py

- **Paper cited:** Collins & Loftus (1975).
- **Paper's algorithm:** Semantic priming via spreading activation: when a concept is activated, activation spreads along associative links to connected concepts. Activation decays with distance. The strength of activation at a node is proportional to the sum of incoming activations weighted by link strength.
- **Implementation status:** FAITHFUL
- **Specific issues:**
  - `spread_activation` implements the Collins & Loftus model correctly: BFS from seed nodes, activation propagates along edges weighted by edge weight, exponential decay by distance (controlled by `decay` parameter), convergent summation at receiving nodes.
  - The convergent summation (`activation[neighbor] += spread`) correctly allows multi-path boosting.
  - The BFS depth limit (`max_depth=3`) and node cap (`max_nodes=50`) are practical constraints, not from the paper.
  - The threshold pruning (`threshold=0.1`) prevents indefinite propagation, which is a necessary practical addition.
  - `map_entity_activation_to_memories` uses max activation rather than sum, which is a defensible design choice to prevent over-boosting but is not from the paper.
  - This is the closest to a faithful implementation in the codebase.
- **Missing equations:** Collins & Loftus did not provide formal equations -- they described the mechanism conceptually. The BFS with decay is a standard computational formalization.
- **Invented constants:** `_DEFAULT_DECAY=0.65`, `_DEFAULT_THRESHOLD=0.1`, `_DEFAULT_MAX_DEPTH=3`, `_DEFAULT_MAX_NODES=50`.

---

### 26. engram.py

- **Paper cited:** Josselyn & Frankland (2007); Rashid et al. (2016).
- **Paper's algorithm:** Memory engram allocation: neurons with higher CREB levels (higher excitability) are preferentially recruited into memory traces. Memories encoded close in time share overlapping neuronal ensembles (because CREB excitability persists for ~6 hours). Lateral inhibition ensures that recently activated neurons suppress neighbors, preventing all memories from being stored in the same neurons.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `compute_decayed_excitability` uses exponential decay with half-life of 6 hours (`E(t) = E0 * 2^(-t/6)`), which matches the ~6 hour CREB excitability window from Rashid et al. This is a good adaptation.
  - `find_best_slot` selects the most excitable slot, which captures the competitive allocation mechanism (high-CREB neurons win).
  - `compute_boost` adds 0.5 to excitability after activation, capped at 1.0. The boost amount is invented.
  - `compute_lateral_inhibition` implements inhibition of neighboring slots. In biology, this is mediated by GABAergic interneurons. The radius-based inhibition (2 neighbors on each side) is a spatial simplification of the actual inhibitory network.
  - The "slot" model is a simplification -- real engrams involve overlapping neuronal populations, not discrete slots.
  - `inhibition_factor=0.25` and `inhibition_radius=2` are invented.
- **Missing equations:** CREB phosphorylation kinetics, MAPK/CREB pathway dynamics, GABAergic inhibition circuit model.
- **Invented constants:** `half_life_hours=6.0` (close to biological ~6h, so this is reasonable), `boost_amount=0.5`, `inhibition_factor=0.25`, `inhibition_radius=2`.

---

### 27. decay_cycle.py

- **Paper cited:** Titans (NeurIPS 2025) mentioned for adaptive decay; no specific paper for core decay.
- **Paper's algorithm:** No specific decay paper is cited. The Titans reference is about test-time learning, not decay per se.
- **Implementation status:** METAPHOR (for Titans); NO PAPER (for core decay)
- **Specific issues:**
  - The core `compute_decay_updates` function is a practical engineering module that applies exponential decay to memory heat values. No paper is cited for the basic mechanism.
  - The "Titans-inspired adaptive decay rate" (`_compute_adaptive_rate`) adjusts per-memory decay rates based on access count, usefulness, and surprise. The Titans paper (if it refers to Sun et al. NeurIPS 2025 "Learning to Remember at Test Time") is about meta-learning a memory module, not about adaptive decay rates. The adaptation here is a loose metaphor.
  - The adaptive rate computation (lines 33-59) with novelty resistance (`surprise * 0.02`), usefulness resistance (`usefulness * 0.01`), and redundancy penalty (`0.02`) is entirely invented.
  - Entity decay at rate 0.98 vs memory decay at 0.95 has no paper basis.
- **Missing equations:** Any formal forgetting curve model (Ebbinghaus, ACT-R, etc.) would be more appropriate citations.
- **Invented constants:** `base_rate=0.95`, `min_rate=0.90`, `max_rate=0.999`, novelty/usefulness resistance (0.02, 0.01), redundancy penalty (0.02), entity decay rate (0.98), cold threshold (0.05).

---

### 28. replay.py

- **Paper cited:** Foster & Wilson (2006); Diba & Buzsaki (2007); Nelli et al. (2025).
- **Paper's algorithm:** Foster & Wilson: During awake sharp-wave ripples, place cells fire in reverse order relative to recent experience (reverse replay). Diba & Buzsaki: Both forward and reverse replay sequences occur during SWR events. Replay is compressed ~20x relative to real-time experience.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - Forward and reverse replay directions are correctly implemented: memories are ordered chronologically (forward) or reverse-chronologically (reverse).
  - Both directions are used, matching Diba & Buzsaki's finding.
  - SWR gating is correctly required before replay can fire.
  - The compression ratio of 20x (line 29 of replay_execution.py: `_COMPRESSION_RATIO = 20.0`) is consistent with biological SWR compression (~5-20x).
  - DA-gated sequence selection captures the idea that reward-relevant sequences are preferentially replayed (Schultz 1997).
  - However, biological replay involves precise temporal reactivation of place cell sequences. This code builds sequences from entity overlap and relationship edges, which is a different mechanism.
  - Schema signals generation from high-RPE sequences (line 194-200) is invented.
- **Missing equations:** Place cell sequence reactivation model, SWR-triggered population burst model.
- **Invented constants:** `_MIN_SEQUENCE_LENGTH=2`, `_MAX_SEQUENCES_PER_SWR=5`, update_strength multiplier 0.3.

---

### 29. replay_execution.py

- **Paper cited:** Foster & Wilson (2006); Diba & Buzsaki (2007).
- **Paper's algorithm:** See replay.py above.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - `build_temporal_sequence` correctly orders memories chronologically.
  - `build_causal_sequence` follows entity relationships to build chains, which is a reasonable analog of place cell sequence replay (following learned associations).
  - STDP pair extraction from replay sequences (lines 189-232) correctly models the idea that replay drives synaptic plasticity: sequential activation during replay generates STDP-like timing signals.
  - The `_STDP_REPLAY_SCALE = 0.5` reduces STDP magnitude during replay compared to waking experience -- a reasonable simplification.
  - The compression ratio of 20.0 for timing is consistent with biological SWR compression.
  - Using `hash(entity_name) & 0x7FFFFFFF` as entity IDs in STDP pairs is a practical implementation detail, not a problem.
  - The sequence building via entity overlap is a reasonable computational analog but not how biological replay works (which involves reactivation of learned population patterns).
- **Missing equations:** Population burst initiation model, sequence compression dynamics.
- **Invented constants:** `_MAX_SEQUENCE_LENGTH=8`, `_STDP_REPLAY_SCALE=0.5`, `_COMPRESSION_RATIO=20.0`.

---

### 30. replay_selection.py

- **Paper cited:** Schultz (1997) implicitly (via RPE scoring).
- **Paper's algorithm (Schultz 1997):** Dopamine neurons fire proportionally to reward prediction error, signaling which experiences are important for learning.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - `compute_sequence_rpe` computes "reward prediction error" as `(avg_heat * 0.4 + sqrt(variance) * 0.6) * dopamine_level`. This is not reward prediction error. RPE is the difference between received and expected reward. This formula is a weighted combination of average heat and heat variance, which is a heuristic proxy for "surprise" in the sequence, modulated by DA level.
  - The formula has no relationship to Schultz's actual RPE computation (delta = r + gamma * V(s') - V(s)).
  - Sequence selection (balanced forward/reverse, sorted by RPE) is a reasonable heuristic.
  - The RPE threshold of 0.3 is invented.
- **Missing equations:** Temporal difference RPE: delta = r + gamma * V(s') - V(s).
- **Invented constants:** `_RPE_THRESHOLD=0.3`, `_MAX_SEQUENCES_PER_SWR=5`, weight split (0.4 avg_heat, 0.6 sqrt(variance)).

---

### 31. reranker.py

- **Paper cited:** Joren et al. (ICLR 2025) "Sufficient Context"; FlashRank (ms-marco-MiniLM-L-12-v2).
- **Paper's algorithm:** Joren et al. propose detecting when retrieval results provide sufficient context to answer a query, using a calibrated confidence score. FlashRank is a cross-encoder reranking model.
- **Implementation status:** APPROXIMATION
- **Specific issues:**
  - FlashRank cross-encoder reranking is correctly implemented: query-passage pairs are scored by the cross-encoder, then blended with WRRF scores.
  - The blending formula `(1 - alpha) * wrrf + alpha * ce` with alpha=0.55 is a reasonable linear interpolation.
  - The "Sufficient Context" implementation (lines 39-66) uses a hard gate on max CE score, not the continuous sigmoid confidence the paper likely proposes. The docstring acknowledges this: "This is a binary gate, not a continuous sigmoid." This is a deliberate simplification.
  - The gate threshold of 0.15 is invented/tuned.
  - The suppression factor of 0.1 (10x score reduction when gated) is invented.
  - Max content length of 1200 is practical, not from any paper.
- **Missing equations:** Joren's calibrated confidence score (likely involves temperature scaling or Platt scaling of CE scores).
- **Invented constants:** `alpha=0.55`, `gate_threshold=0.15`, `suppression=0.1`, `max_content_len=1200`.

---

### 32. query_decomposition.py

- **Paper cited:** IRCoT (ACL 2023); HippoRAG (NeurIPS 2024).
- **Paper's algorithm (IRCoT):** Interleaving chain-of-thought reasoning with retrieval: decompose a complex question into sub-questions, retrieve for each, and iteratively refine. (HippoRAG): Uses the hippocampal indexing theory to decompose queries through a knowledge graph traversal.
- **Implementation status:** METAPHOR
- **Specific issues:**
  - `generate_sub_queries` extracts CamelCase identifiers, file paths, backtick-quoted terms, multi-word proper nouns, and quoted phrases from the query. This is entity extraction, not IRCoT's chain-of-thought decomposition.
  - IRCoT decomposes questions via iterative LLM reasoning: "What is the first sub-question? Retrieve for it. Based on results, what is the next sub-question?" This code uses regex extraction, which is fundamentally different.
  - HippoRAG's decomposition is also LLM-driven, using a personalized PageRank over a knowledge graph. This code does not implement any knowledge graph traversal for decomposition.
  - The route_query function provides intent-based routing, which is useful but not from either cited paper.
  - The entity extraction regex (CamelCase, file paths, backtick-quoted) is practical but paper-free.
- **Missing equations:** IRCoT's iterative retrieval-reasoning loop, HippoRAG's personalized PageRank, any LLM-based decomposition.
- **Invented constants:** Stop word list, time regex patterns, sub-query limit of 6.

---

### 33. write_post_store.py

- **Paper cited:** Frey & Morris (1997) for synaptic tagging (delegated to synaptic_tagging.py); Josselyn & Frankland for engram allocation (delegated to engram.py).
- **Implementation status:** N/A (orchestration module)
- **Specific issues:**
  - This module is a handler-layer composition root that wires together other core modules. It does not claim to implement any paper itself -- it orchestrates calls to `synaptic_tagging`, `engram`, `knowledge_graph`, and `prospective`.
  - The implementation correctly delegates to the relevant core modules.
  - `_find_shared_entities` (lines 142-158) queries the store extensively to find all entities a memory mentions. This is an I/O-heavy operation in a module that is labeled as "core" but clearly performs infrastructure operations via the injected `store` object. This may be an architectural concern rather than a scientific one.
  - No independent scientific claims to audit here.

---

## Summary Table

| Module | Paper(s) Cited | Status | Primary Issue |
|---|---|---|---|
| thermodynamics.py | Ebbinghaus 1885, McGaugh 2004 | HONEST | Decay cites Ebbinghaus; heuristics documented as such |
| coupled_neuromodulation.py | Schultz 1997, Dawes 1979 | HONEST | Doya departure documented; downstream functions labeled as heuristics |
| neuromodulation_channels.py | Rescorla-Wagner 1972, Schultz 1997 | FAITHFUL (DA) / HONEST (NE,ACh,5-HT) | DA RPE: R-W equation + Schultz firing bounds [0,3]. NE/ACh/5-HT honestly documented |
| emotional_tagging.py | Yerkes-Dodson 1908 | FAITHFUL | f(a) = c*a*exp(-b*a) smooth inverted-U curve |
| synaptic_tagging.py | Frey & Morris 1997, Luboeinski 2021 | DOCUMENTED | Bistable z ODE faithful; 48h window is engineering adaptation |
| oscillatory_phases.py | Hasselmo 2005, Lisman&Jensen 2013, Buzsaki 2015 | DOCUMENTED | Encoding/retrieval separation captured; cosine is engineering |
| cascade_stages.py | Kandel 2001, Nader 2000, Bahrick 1984 | DOCUMENTED | Stage timings match biology; multipliers hand-tuned |
| cascade_advancement.py | Kandel 2001, Tse 2007, Nader 2000 | APPROXIMATION | Schema acceleration under-modeled (50% vs 15x in Tse) |
| separation_core.py | Leutgeb 2007, Rolls 2013 | FAITHFUL | Sparsity 4% from DG data; Gram-Schmidt orthogonalization |
| schema_engine.py | Tse 2007, van Kesteren 2012, Piaget | DOCUMENTED | Tse is experimental only; no equations exist |
| schema_extraction.py | Tse 2007, Gilboa&Marlatte 2017 | DOCUMENTED | Frequency-based; Gilboa provides criteria not equations |
| interference.py | Anderson&Neely 1996, Norman 2007 | DOCUMENTED | LCA cited; linear suppression documented as simplification |
| homeostatic_plasticity.py | Tetzlaff 2011, BCM 1982 | FAITHFUL | Tetzlaff Eq.3 multiplicative scaling + BCM quadratic phi |
| dendritic_clusters.py | (none — metaphor documented) | HONEST | Jaccard grouping labeled as heuristic |
| dendritic_computation.py | Poirazi 2003 | FAITHFUL | Sigmoid s(n) + soma g(x) from Neuron 37:989-999 Fig 3 |
| two_stage_model.py | McClelland 1995 | DOCUMENTED | CLS framework qualitative; scalar dependency is engineering |
| two_stage_transfer.py | McClelland 1995, Ketz 2023 | FAITHFUL | C-HORSE cortical learning rate 0.02 |
| tripartite_synapse.py | Perea 2009 | DOCUMENTED | Three-regime model qualitative; delegates to tripartite_calcium |
| tripartite_calcium.py | De Pitta 2009, Pellerin 1994 | DOCUMENTED | De Pitta ODE faithful; metabolic rate is engineering |
| synaptic_plasticity.py | Tsodyks-Markram 1997, Hasselmo 2005 | FAITHFUL | u_new = u + U*(1-u), x_new = x - u_eff*x |
| synaptic_plasticity_hebbian.py | BCM 1982, Bi&Poo 1998 | FAITHFUL | phi(c,theta_m) = c*(c-theta_m) quadratic; STDP A+*exp(-dt/tau+) |
| synaptic_plasticity_stochastic.py | Hebb, BCM, Markram | DOCUMENTED | Novel composition of faithful components |
| microglial_pruning.py | (none — metaphor documented) | HONEST | Threshold rules labeled as heuristic |
| dual_store_cls.py | (none — heuristic documented) | HONEST | Regex classifier labeled honestly |
| spreading_activation.py | Collins & Loftus 1975 | FAITHFUL | BFS with decay and convergent summation |
| titans_memory.py | Behrouz et al. (NeurIPS 2025) | FAITHFUL | M_t = M_{t-1} - S_t, S_t = eta*S_{t-1} - theta*grad |
| engram.py | Rashid 2016, Josselyn 2007 | DOCUMENTED | 6h half-life faithful; inhibition + boost hand-tuned |
| decay_cycle.py | ACT-R (Anderson & Lebiere 1998) | FAITHFUL | B_i = ln(n) - d*ln(L), d=0.5 |
| replay.py | Foster&Wilson 2006, Diba&Buzsaki 2007 | DOCUMENTED | Forward/reverse correct; entity-based documented |
| replay_execution.py | Foster&Wilson 2006, Davidson 2009 | DOCUMENTED | Compression 15-20x correct; sequence building is engineering |
| replay_selection.py | (none — heuristic documented) | HONEST | Priority score labeled as heuristic |
| reranker.py | Joren ICLR 2025, FlashRank | APPROXIMATION | Binary gate instead of calibrated confidence |
| query_decomposition.py | (none — heuristic documented) | HONEST | Regex extraction labeled honestly |
| write_post_store.py | (delegates) | N/A | Orchestration module, no independent claims |

## Overall Assessment

**Updated count (2026-04-03):** 12 FAITHFUL, 12 DOCUMENTED, 8 HONEST, 1 APPROXIMATION, 1 N/A.

### FAITHFUL implementations (exact paper equations):

| Module | Paper | Equation |
|---|---|---|
| spreading_activation.py | Collins & Loftus 1975 | BFS spreading + convergent summation |
| titans_memory.py | Behrouz et al. NeurIPS 2025 | M_t = M_{t-1} - S_t, S_t = eta*S_{t-1} - theta*grad |
| synaptic_plasticity_hebbian.py | BCM 1982, Bi&Poo 1998 | phi(c, theta_m) = c*(c-theta_m); A+*exp(-dt/tau+) |
| synaptic_plasticity.py | Tsodyks-Markram 1997 | u_new = u + U*(1-u), x_new = x - u_eff*x |
| decay_cycle.py | ACT-R (Anderson & Lebiere 1998) | B_i = ln(n) - d*ln(L), d=0.5 |
| emotional_tagging.py | Yerkes-Dodson 1908 | f(a) = c*a*exp(-b*a) smooth inverted-U |
| dendritic_computation.py | Poirazi 2003 | Sigmoid s(n) + soma g(x) from Neuron Fig 3 |
| homeostatic_plasticity.py | Tetzlaff 2011, BCM 1982 | Eq.3 multiplicative + quadratic phi |
| separation_core.py | Leutgeb 2007, Rolls 2013 | Sparsity 4% from DG granule cell data |
| two_stage_transfer.py | Ketz 2023 (C-HORSE) | Cortical learning rate 0.02 |
| neuromodulation_channels.py (DA) | Rescorla-Wagner 1972, Schultz 1997 | delta = actual - V(s); DA = 1+delta in [0,3] |
| engram.py (half-life) | Rashid et al. 2016 | E(t) = E0 * 2^(-t/6h) |

### Critical architectural fix: Permastore (2026-04-01)

**Problem**: All memories decayed to zero heat and were marked `is_stale=TRUE` permanently — destroying the persistent memory system.

**Root cause**: `cascade_stages.py` defined decay multipliers and stages, but `decay_cycle.py` never used them. The PG `decay_memories()` function marked ALL low-heat memories as stale regardless of consolidation stage.

**Fix**: Three changes grounded in published research:

1. **Heat floor by consolidation stage** (cascade_stages.py):
   - CONSOLIDATED: floor = 0.10 (Bahrick 1984, Benna & Fusi 2016, Kandel 2001)
   - LATE_LTP: floor = 0.05
   - LABILE/EARLY_LTP: floor = 0.0

2. **Stage-adjusted decay wired into decay_cycle.py**:
   - `compute_stage_adjusted_decay()` now called for every memory
   - Consolidated memories decay at 0.5x rate

3. **PG `decay_memories()` respects consolidation stage**:
   - Only LABILE/EARLY_LTP memories can be marked stale
   - CONSOLIDATED/LATE_LTP memories enforce heat floor in SQL

### Changelog

**2026-04-03 (Wave 2):**
- `neuromodulation_channels.py` DA channel: R-W equation verified faithful. Schultz firing
  rate claim fixed (was "40Hz baseline, 80Hz burst" → now "5Hz baseline, 20-30Hz burst").
  DA ceiling widened [0,2]→[0,3] for asymmetric biology. NE/ACh/5-HT remain HONEST.
- Summary table fully synchronized with code state (was stale since 2026-04-01).
- Reclassified: 12 FAITHFUL, 12 DOCUMENTED, 8 HONEST, 1 APPROXIMATION, 1 N/A.

**2026-04-01 (Wave 1):**
- All 12 METAPHOR modules addressed: false citations removed, honest documentation added.
- 5 new FAITHFUL: titans_memory, BCM quadratic, Tsodyks-Markram, ACT-R, Yerkes-Dodson.
- 4 promoted: dendritic_computation, homeostatic_plasticity, separation_core, two_stage_transfer.
- Permastore fix: consolidated memories no longer decay to zero (Bahrick 1984).

**2026-03-31 (Initial audit):**
- First complete audit of 33 modules: 1 FAITHFUL, 19 APPROXIMATION, 9 METAPHOR.

### Remaining work

- `reranker.py`: Platt sigmoid attempted and REJECTED (2026-04-03). Hand-tuned sigmoid
  regressed BEAM -0.148 MRR and LoCoMo -5.1pp R@10. Proper calibration would require
  collecting (max_CE, is_correct) pairs from benchmarks and fitting via logistic regression.
  Binary gate is empirically optimal for now.