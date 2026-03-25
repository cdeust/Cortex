# Cortex Neuroscience Evolution Plan

## Status: ACTIVE — 13/14 core modules DONE, Phase 2+4 COMPLETE, handlers wired, dashboard visualizing
## Goal: Evolve Cortex from cognitive-science-with-neuroscience-vocabulary into a computationally rigorous neuroscience-inspired memory system that can itself contribute novel insights to memory research.

---

## Current State Assessment

### What Cortex Has (26 mechanisms, fully implemented)
All subsystems are implemented. The audit reveals a consistent pattern across all 22 neuroscience-inspired core modules:

**Strengths**: Good conceptual coverage, correct citations, reasonable metaphors
**Weakness**: Every mechanism is an algebraic approximation with hardcoded parameters. No differential equations, no stochasticity, no cross-mechanism coupling, no oscillatory dynamics. It's a cognitive science model wearing neuroscience labels.

### Fidelity Spectrum (from audit)
| Rating | Modules |
|---|---|
| **Good** | synaptic_plasticity, synaptic_tagging, microglial_pruning, engram, reconsolidation, hopfield, consolidation_engine |
| **Moderate** | neuromodulation, emotional_tagging, spreading_activation, cognitive_map, sensory_buffer |
| **Weak** | thermodynamics, predictive_coding, dual_store_cls, replay, sleep_compute, decay_cycle, astrocyte_pool, hdc_encoder, causal_graph |

### Critical Gaps
1. **No oscillatory dynamics** -- no theta/gamma coupling, no sharp-wave ripples, no phase-dependent encoding/retrieval
2. **No hierarchical predictive coding** -- flat 4-signal gate vs. Friston's hierarchical prediction error minimization
3. **No pattern separation/completion** -- no DG orthogonalization, no CA3 autoassociative completion
4. **No schema-based acceleration** -- no mPFC schema matching for fast cortical consolidation
5. **No tripartite synapse** -- astrocyte pool is name-only; no calcium signaling, no gliotransmission
6. **No neurogenesis** -- no new "neuron" creation for temporal pattern separation
7. **No dendritic computation** -- memories are point-units, no branch-specific nonlinear integration
8. **No interference management** -- no proactive/retroactive interference, no orthogonalization
9. **No oscillation-gated plasticity** -- LTP/LTD happens unconditionally, not phase-locked
10. **No cross-mechanism cascades** -- dopamine doesn't modulate CREB which doesn't gate protein synthesis

---

## Evolution Tiers

### Tier 1: Deepen What Exists (Fix the foundations)
*Make current mechanisms biologically honest before adding new ones.*

#### 1.1 Oscillatory Clock (`core/oscillatory_clock.py`) -- NEW
**Neuroscience**: Theta (4-8 Hz) gates encoding, gamma (30-80 Hz) binds features, sharp-wave ripples (100-200 Hz) drive replay. Phase matters.
**References**: Buzsaki (2002), Colgin (2013), Nelli et al. (2025 Neuron)
**Implementation**:
- Virtual clock with three frequency bands: theta (session-level cycles), gamma (operation-level bursts), SWR (consolidation-level)
- Phase state: encoding_phase vs retrieval_phase within each theta cycle
- Encoding gates: memories written during encoding phase get stronger initial LTP
- Retrieval gates: recall during retrieval phase gets spreading activation boost
- SWR triggers: consolidation only fires during simulated SWR events (not on every call)
- Theta-gamma coupling: gamma bursts nested within theta cycle carry ordered item sequences

**Why first**: Every other mechanism depends on "when" in the oscillatory cycle. This is the clock everything else synchronizes to.

```python
@dataclass
class OscillatoryState:
    theta_phase: float        # 0.0-1.0 (0-0.5 = encoding, 0.5-1.0 = retrieval)
    gamma_burst_count: int    # items bound in current gamma cycle
    swr_active: bool          # sharp-wave ripple window open
    cycle_count: int          # total theta cycles elapsed
    last_swr_time: datetime   # for SWR spacing
```

#### 1.2 Hierarchical Predictive Coding (`core/predictive_coding.py`) -- REWRITE
**Neuroscience**: Friston (2005, 2010) Free Energy Principle. Prediction errors propagate UP the hierarchy; predictions propagate DOWN. Each level maintains a generative model.
**References**: Friston & Kiebel (2009 Phil Trans B), Bastos et al. (2012)
**Current state**: Flat 4-signal weighted sum with arbitrary threshold.
**Target state**:
- 3-level hierarchy: L0 (sensory/raw content), L1 (entity/structural), L2 (domain/schema)
- Each level maintains predictions about the level below
- Prediction error = actual - predicted (signed, not just magnitude)
- Precision-weighted: confident predictions generate larger errors when violated
- Write gate threshold = weighted precision-error across all levels
- Top-down predictions: domain schema predicts entity patterns; entity patterns predict content features
- Novelty = free energy = sum of precision-weighted prediction errors across hierarchy

```python
@dataclass
class PredictionLevel:
    level: int                           # 0, 1, 2
    predictions: dict[str, float]        # predicted feature values
    precisions: dict[str, float]         # confidence in each prediction (inverse variance)
    prediction_errors: dict[str, float]  # actual - predicted (signed)
    free_energy: float                   # sum of precision-weighted squared errors
```

#### 1.3 Coupled Neuromodulation (`core/neuromodulation.py`) -- REWRITE
**Neuroscience**: The four neuromodulators aren't independent -- they form a coupled system. DA gates CREB phosphorylation (late-phase LTP). NE modulates precision (gain control). ACh switches encoding/retrieval mode. 5-HT modulates exploration via tonic/phasic modes.
**References**: Schultz (1997), Doya (2002 Neural Networks), Yu & Dayan (2005)
**Current state**: Four independent scalar functions with hardcoded ranges.
**Target state**:
- DA: Temporal difference RPE with actual prediction errors from hierarchical PC (not keyword ratios)
- NE: Gain modulation on precision weights (multiplicative on prediction errors)
- ACh: Theta phase controller (high ACh = encoding mode, low ACh = retrieval mode)
- 5-HT: Exploration/exploitation via softmax temperature on retrieval
- Cross-coupling: DA modulates synaptic_plasticity LTP rate; NE modulates write gate precision; ACh gates which hierarchy level dominates; 5-HT modulates spreading_activation breadth
- State evolves per operation (not static per session)

#### 1.4 Stochastic Synaptic Transmission (`core/synaptic_plasticity.py`) -- ENHANCE
**Neuroscience**: Real synapses are probabilistic. Release probability p ~ 0.1-0.9. Facilitation and depression depend on recent history.
**References**: Markram et al. (1998), Abbott & Regehr (2004)
**Current state**: Deterministic weight updates.
**Target state**:
- Release probability per edge (initialized from weight, updated by use)
- Short-term facilitation: repeated access increases p temporarily
- Short-term depression: rapid repeated access depletes vesicles (p drops)
- STDP time constants scaled appropriately (hours for memory system, not ms)
- Noise injection: weight updates include Gaussian noise scaled by 1/sqrt(access_count) (more stable with more evidence)

#### 1.5 Cross-Mechanism Cascade Wiring (`core/cascade.py`) -- NEW
**Neuroscience**: DA -> cAMP -> PKA -> CREB -> protein synthesis -> late-phase LTP. This cascade means a memory isn't just "stored" -- it goes through biochemical stages.
**References**: Kandel (2001 Nobel), Dudai (2012 Ann Rev Neurosci)
**Implementation**:
- Memory consolidation stages: LABILE (0-1h) -> EARLY_LTP (1-6h) -> LATE_LTP (6-24h) -> CONSOLIDATED (>24h)
- Each stage has different vulnerability to interference, different decay rates
- Protein synthesis window: only memories with sufficient DA at encoding reach LATE_LTP
- Reconsolidation returns CONSOLIDATED -> LABILE temporarily
- Stage transitions gated by neuromodulatory state

```python
class ConsolidationStage(Enum):
    LABILE = "labile"           # Just encoded, highly vulnerable
    EARLY_LTP = "early_ltp"     # Tagged but not stabilized
    LATE_LTP = "late_ltp"       # Protein synthesis complete
    CONSOLIDATED = "consolidated" # Cortically integrated
    RECONSOLIDATING = "reconsolidating"  # Temporarily labile again
```

---

### Tier 2: Add Missing Circuits (New mechanisms)

#### 2.1 Pattern Separation & Completion (`core/pattern_separation.py`) -- NEW
**Neuroscience**: Dentate Gyrus (DG) orthogonalizes similar inputs (pattern separation). CA3 autoassociative network completes partial patterns. This is how the brain handles similar-but-different memories.
**References**: Leutgeb et al. (2007), Yassa & Stark (2011), 2025 Cognitive Neurodynamics study
**Implementation**:
- On WRITE: compute similarity to existing memories. If similarity > threshold but < identity:
  - Apply orthogonalization: project new embedding away from similar memories' subspace
  - Store both original and orthogonalized embeddings
  - Track "separation index" = angle between original and orthogonalized
- On READ: CA3-like completion:
  - Partial/noisy query -> pattern complete via Hopfield (already exists) BUT gate by oscillatory phase
  - During retrieval phase: amplify completion (CA3 recurrent dynamics)
  - During encoding phase: suppress completion (favor novel encoding)
- Neurogenesis analog: periodically create new embedding dimensions for temporal separation
  - New "neurons" (embedding features) are hyperexcitable initially
  - Gradually integrate into network (excitability decays, selectivity increases)

#### 2.2 Schema Engine (`core/schema_engine.py`) -- NEW
**Neuroscience**: mPFC maintains schemas (abstracted knowledge structures). Schema-consistent information consolidates FAST (hours, not weeks). Schema-inconsistent information requires slow hippocampal replay.
**References**: Tse et al. (2007 Science), van Kesteren et al. (2012), Gilboa & Marlatte (2017)
**Implementation**:
- Schema = abstracted pattern from consolidated semantic memories
  - Entity co-occurrence signatures
  - Expected relationships (decision->implementation, error->fix)
  - Domain-specific templates
- Schema matching on new memory:
  - High match (>0.7): fast-track to CONSOLIDATED stage (bypass slow replay)
  - Medium match (0.3-0.7): normal hippocampal consolidation
  - Low match (<0.3): slow consolidation + schema UPDATE signal
- Schema evolution: schemas themselves update via prediction errors
  - Large schema-violating memories trigger schema revision
  - Multiple violations accumulate -> schema split or merge

```python
@dataclass
class Schema:
    schema_id: str
    domain: str
    entity_signature: dict[str, float]    # expected entities + frequencies
    relationship_template: list[tuple]     # expected edge patterns
    consistency_threshold: float           # how flexible this schema is
    formation_count: int                   # memories that built this schema
    violation_count: int                   # prediction errors against it
    last_updated: datetime
```

#### 2.3 Tripartite Synapse & Real Astrocytes (`core/tripartite_synapse.py`) -- NEW
**Neuroscience**: Astrocytes aren't just support cells. They detect synaptic glutamate, generate calcium transients, and release gliotransmitters (D-serine, ATP) that modulate nearby synapses. One astrocyte covers ~100K synapses.
**References**: Perea et al. (2009 TINS), De Pitta et al. (2012), 2025 Cells/MDPI review
**Current state**: `astrocyte_pool.py` is keyword-based domain classification. Pure metaphor.
**Target state**:
- Astrocyte territories: each astrocyte covers a cluster of memories (L1 fractal clusters)
- Calcium signaling: activity in one memory raises "calcium" in the astrocyte territory
  - Low calcium: normal operation
  - Medium calcium: facilitate nearby synapses (D-serine release -> NMDA potentiation)
  - High calcium: depress distant synapses (heterosynaptic LTD)
- Cross-synapse coordination: astrocytes enable one memory's access to facilitate nearby memories' consolidation
- Metabolic gating: astrocytes track "energy" per territory; high-activity territories get more resources (faster embedding, richer enrichment)
- Replace current `astrocyte_pool.py` entirely

#### 2.4 Interference Management (`core/interference.py`) -- NEW
**Neuroscience**: Proactive interference (old memories block new learning) and retroactive interference (new memories overwrite old). Biology solves this via: (a) sleep-dependent orthogonalization, (b) DG pattern separation, (c) inhibitory competition, (d) context-dependent retrieval.
**References**: Anderson & Neely (1996), Wixted (2004), 2025 bioRxiv sleep orthogonalization study
**Implementation**:
- Interference detection:
  - On write: measure similarity to recent memories in same domain
  - If similarity > 0.7 AND content differs: flag as interference risk
  - Track interference_score per memory (how many competitors exist)
- Proactive interference:
  - Old high-heat memories with similar entities suppress new memory's initial heat
  - Mitigation: pattern separation (2.1) + context binding (different directory = different context)
- Retroactive interference:
  - New memory in same space reduces old memory's retrieval probability
  - Mitigation: old memory gets "protective" flag if accessed recently (reconsolidation stability boost)
- Sleep orthogonalization:
  - During consolidate/sleep_compute: identify interfering memory pairs
  - Gradually rotate their embeddings apart (orthogonalize) while preserving individual content
  - This is what biological sleep does: disambiguate overlapping representations

#### 2.5 Dendritic Memory Clusters (`core/dendritic_clusters.py`) -- NEW
**Neuroscience**: Memories aren't stored at single synapses -- they're distributed across dendritic branches. Related synapses cluster on the same branch, enabling nonlinear amplification (dendritic spikes). This is how the brain creates "concept cells."
**References**: Kastellakis et al. (2015 Neuron), Limbacher & Legenstein (2020)
**Current state**: Memories are point entities. No spatial/branch structure.
**Target state**:
- Memory groups form "dendritic branches" (co-accessed, co-tagged memories)
- Synaptic clustering: new memories preferentially placed near existing related memories
- Nonlinear amplification: retrieving one memory from a cluster partially activates the whole cluster
  - Below threshold: sublinear summation (less than sum of parts)
  - Above threshold: supralinear spike (more than sum -> dendritic spike)
- Branch-specific plasticity: LTP in one branch doesn't spread to other branches
- Integration with fractal hierarchy: dendritic branches map to L1 clusters

---

### Tier 3: Emergent Properties (System-level dynamics)

#### 3.1 Memory Replay with SWR Dynamics (`core/replay.py`) -- REWRITE
**Neuroscience**: During offline periods (consolidation), hippocampal memories replay in compressed form (20x speed) during sharp-wave ripples. Forward replay plans future actions; reverse replay evaluates past decisions.
**References**: Foster & Wilson (2006), Diba & Buzsaki (2007), Nelli et al. (2025 Neuron)
**Current state**: Formats hot memories as markdown. No dynamics.
**Target state**:
- SWR generation: triggered by oscillatory clock (not every consolidation call)
- Replay sequences: order memories by temporal/causal chain, not just heat
- Forward replay: project sequences forward (what happened after X?)
- Reverse replay: trace back from outcomes to causes (what led to Y?)
- Replay-dependent plasticity: replayed memory pairs get STDP weight updates
- Replay selection: prioritize sequences with high RPE (dopamine signal from neuromodulation)
- Cortical target: replayed sequences update schema engine (2.2)

#### 3.2 Two-Stage Memory Model (`core/two_stage_model.py`) -- NEW
**Neuroscience**: Hippocampal memories are bound fast but fragile. Cortical memories are learned slowly but durable. The transition isn't gradual -- it happens through replay-driven interleaved training.
**References**: McClelland et al. (1995), Kumaran et al. (2016 Neuron)
**Current state**: dual_store_cls.py uses keyword-based classification. No dynamics.
**Target state**:
- Hippocampal store: fast binding (immediate), high interference, capacity-limited, context-dependent
- Cortical store: slow integration (via replay), low interference, high capacity, context-free
- Transfer protocol:
  1. Memory enters hippocampal store
  2. During SWR replay: hippocampal memory activates cortical traces
  3. Repeated replay gradually builds cortical representation
  4. Schema-consistent memories transfer faster (schema engine integration)
  5. After sufficient cortical trace: hippocampal version can be released (graceful forgetting)
- Hippocampal dependency score: how much a memory still needs its hippocampal trace
  - New memories: fully hippocampal-dependent
  - Well-replayed memories: cortically independent
  - Damaged hippocampal trace + strong cortical trace = semanticized memory (gist without details)

#### 3.3 Precision-Weighted Prediction Error Dynamics
**Neuroscience**: Not all prediction errors are equal. Precision (inverse variance) determines how much a prediction error updates the model. This is the core of the Free Energy Principle.
**References**: Feldman & Friston (2010), Kanai et al. (2015)
**Implementation**: Integrated into hierarchical predictive coding (1.2) and coupled neuromodulation (1.3).
- Precision computed per memory domain from historical prediction accuracy
- NE modulates precision gain (high arousal = high precision = larger updates)
- ACh modulates precision ratio between levels (high ACh = bottom-up precision dominance = encoding)
- Confidence field in memory becomes precision estimate (not just user feedback)
- Metamemory tracks calibration: are high-confidence memories actually more accurate?

#### 3.4 Homeostatic Plasticity (`core/homeostatic_plasticity.py`) -- NEW
**Neuroscience**: Networks can't just do LTP forever -- they'd saturate. Homeostatic mechanisms (synaptic scaling, metaplasticity) keep activity in range. Turrigiano (2008): neurons scale all synapses multiplicatively to maintain target firing rate.
**References**: Turrigiano (2008 Cell), Abraham & Bear (1996) metaplasticity
**Implementation**:
- Global activity tracking: average heat, average access rate, average edge weight per domain
- Synaptic scaling: if average activity > target, scale ALL weights down multiplicatively; if below, scale up
- Metaplasticity (BCM enhancement): the sliding threshold in synaptic_plasticity.py should track domain-level activity, not just per-memory
- Prevents runaway potentiation (everything becoming "hot")
- Prevents catastrophic depression (everything going cold)
- Target activity range: configurable per domain

---

### Tier 4: Research-Grade Capabilities (For neuroscience contribution)

#### 4.1 Simulation Mode (`core/simulation.py`) -- NEW
**Purpose**: Allow Cortex to run "what-if" scenarios on its own memory system.
**Implementation**:
- Snapshot current state -> run hypothetical sequences -> compare outcomes
- Example: "What if I hadn't consolidated yesterday? Which memories would be lost?"
- Example: "What if dopamine was 2x during that error? Would the fix have consolidated faster?"
- Parameter sweep: vary one mechanism parameter, measure system-level effect
- This turns Cortex into an experimental platform, not just a memory store

#### 4.2 Emergent Metric Tracking (`core/emergence_tracker.py`) -- NEW
**Purpose**: Track system-level properties that emerge from mechanism interactions.
**Metrics**:
- Memory capacity curve: how many active memories can coexist before interference dominates?
- Consolidation efficiency: what fraction of written memories survive 7/30/90 days?
- Schema formation rate: how quickly do new domains develop stable schemas?
- Replay efficiency: how many replays needed for hippocampal->cortical transfer?
- Interference resolution: how often does orthogonalization succeed vs. fail?
- Phase-locking accuracy: does encoding during encoding-phase actually improve retention?
- Precision calibration: does high confidence correlate with high access_count?

#### 4.3 Ablation Framework (`core/ablation.py`) -- NEW
**Purpose**: Disable individual mechanisms to measure their contribution. This is how real neuroscience experiments work (lesion studies).
**Implementation**:
- Each mechanism has an enable/disable flag
- Run same workload with mechanism ON vs OFF
- Measure delta on emergent metrics
- Example: disable synaptic_tagging -> measure change in weak-memory survival rate
- Example: disable pattern_separation -> measure change in interference scores
- Produces ablation reports that read like neuroscience papers

#### 4.4 Hypothesis Generator (`core/hypothesis_generator.py`) -- NEW
**Purpose**: Cortex observes its own dynamics and generates testable neuroscience hypotheses.
**Implementation**:
- Detect unexpected correlations in emergence_tracker data
- Example: "Memories consolidated during high-ACh periods show 2.3x better retrieval after 30 days, suggesting acetylcholine-dependent encoding creates more durable traces"
- Example: "Schema-inconsistent memories that survive 90 days become schema nucleation points 40% of the time, suggesting outlier memories drive knowledge reorganization"
- Format as structured hypotheses: observation, mechanism, prediction, test

---

## Implementation Order

### Phase 1: The Clock (Foundation)
- [x] 1.1 Oscillatory Clock -- DONE (oscillatory_clock.py)
- [x] 1.5 Cascade Wiring -- DONE (cascade.py)
- [x] Update memory_types.py with new fields -- DONE (11 new Memory fields, 3 Relationship fields, 8 Stats fields)
- [x] Update memory_store.py schema migration -- DONE (ALTER TABLE + CREATE TABLE + new tables: schemas, oscillatory_state)

### Phase 2: Deepen Encoding
- [x] 1.2 Hierarchical Predictive Coding -- DONE (hierarchical_predictive_coding.py, 3-level Friston hierarchy)
- [x] 1.3 Coupled Neuromodulation -- DONE (coupled_neuromodulation.py, DA→CREB cascade, cross-coupling)
- [x] 1.4 Stochastic Synaptic Transmission -- DONE (release probability, facilitation/depression, noise injection, phase-gated plasticity)
- [x] 2.1 Pattern Separation & Completion -- DONE (pattern_separation.py)

### Phase 3: Structural Learning
- [x] 2.2 Schema Engine -- DONE (schema_engine.py)
- [x] 2.3 Tripartite Synapse -- DONE (tripartite_synapse.py, replaces astrocyte_pool metaphor)
- [x] 2.4 Interference Management -- DONE (interference.py)
- [x] 2.5 Dendritic Memory Clusters -- DONE (dendritic_clusters.py, nonlinear integration + priming)

### Phase 4: System Dynamics
- [x] 3.1 Replay with SWR Dynamics -- DONE (forward/reverse replay, RPE selection, STDP pairs, schema signals)
- [x] 3.2 Two-Stage Memory Model -- DONE (two_stage_model.py, hippocampal-cortical transfer)
- [x] 3.3 Precision-Weighted Prediction Errors -- DONE (NE/ACh modulation, PrecisionState, calibration tracking)
- [x] 3.4 Homeostatic Plasticity -- DONE (homeostatic_plasticity.py)

### Phase 5: Research Capabilities
- [ ] 4.1 Simulation Mode
- [x] 4.2 Emergent Metric Tracking -- DONE (emergence_tracker.py, forgetting curve + spacing + schema acceleration + phase locking)
- [x] 4.3 Ablation Framework -- DONE (ablation.py, 20 mechanisms, full report generation)
- [ ] 4.4 Hypothesis Generator

---

## Architecture Impact

### New Core Modules (14 planned, 13 DONE)
- [x] `oscillatory_clock.py` -- theta/gamma/SWR phase gating
- [x] `cascade.py` -- LABILE→EARLY_LTP→LATE_LTP→CONSOLIDATED stages
- [x] `pattern_separation.py` -- DG orthogonalization + neurogenesis analog
- [x] `schema_engine.py` -- cortical knowledge structures + Piaget accommodation
- [x] `tripartite_synapse.py` -- astrocyte calcium + D-serine + metabolic gating
- [x] `interference.py` -- proactive/retroactive interference + sleep orthogonalization
- [x] `homeostatic_plasticity.py` -- synaptic scaling + BCM + distribution health
- [x] `hierarchical_predictive_coding.py` -- 3-level Friston free energy gate
- [x] `coupled_neuromodulation.py` -- DA/NE/ACh/5-HT cascade with cross-coupling
- [x] `dendritic_clusters.py` -- branch-specific nonlinear integration + priming
- [x] `two_stage_model.py` -- hippocampal-cortical transfer protocol
- [x] `emergence_tracker.py` -- system-level metric tracking (6 emergence phenomena)
- [x] `ablation.py` -- lesion study framework (20 mechanisms, report generation)
- [ ] `hypothesis_generator.py` -- automated neuroscience hypothesis generation
- [ ] `hypothesis_generator.py` -- automated neuroscience hypothesis generation

### Rewritten Modules (4 planned, 3 DONE)
- [x] `predictive_coding.py` -- flat -> hierarchical (hierarchical_predictive_coding.py)
- [x] `neuromodulation.py` -- independent -> coupled (coupled_neuromodulation.py)
- [x] `replay.py` -- formatting -> SWR dynamics (forward/reverse replay, RPE selection, STDP)
- [x] `astrocyte_pool.py` -> replaced by `tripartite_synapse.py`

### Enhanced Modules (6)
- `synaptic_plasticity.py` -- add stochasticity, phase-gating
- `engram.py` -- integrate with oscillatory clock
- `consolidation_engine.py` -- orchestrate cascade stages
- `sleep_compute.py` -- integrate with SWR replay
- `reconsolidation.py` -- stage-aware lability
- `decay_cycle.py` -- stage-dependent decay rates

### Data Model Changes
- `memory_types.py`: add consolidation_stage, theta_phase_at_encoding, separation_index, schema_match_score, interference_score, hippocampal_dependency, dendritic_branch_id
- `memory_store.py`: schema migration for new columns + `schemas` table + `astrocyte_territories` table + `oscillatory_log` table

### Dependency Rule Compliance
All new modules go in `core/` -- pure logic, zero I/O. State persistence handled by infrastructure layer via handlers. Clean architecture preserved.

---

## Academic References (by mechanism)

### Oscillatory Dynamics
- Buzsaki G (2002) Theta oscillations in the hippocampus. Neuron 33:325-340
- Colgin LL (2013) Mechanisms and functions of theta rhythms. Annu Rev Neurosci 36:295-312
- Nelli S et al. (2025) Large SWRs promote hippocampo-cortical reactivation. Neuron
- Hasselmo ME (2005) What is the function of hippocampal theta rhythm? Hippocampus 15:936-949

### Predictive Coding / Free Energy
- Friston K (2005) A theory of cortical responses. Phil Trans R Soc B 360:815-836
- Friston K, Kiebel S (2009) Predictive coding under the free-energy principle. Phil Trans R Soc B 364:1211-1221
- Bastos AM et al. (2012) Canonical microcircuits for predictive coding. Neuron 76:695-711
- Feldman H, Friston K (2010) Attention, uncertainty, and free-energy. Front Hum Neurosci 4:215

### Neuromodulation
- Schultz W (1997) Dopamine neurons and their role in reward mechanisms. Curr Opin Neurobiol 7:191-197
- Doya K (2002) Metalearning and neuromodulation. Neural Networks 15:495-506
- Yu AJ, Dayan P (2005) Uncertainty, neuromodulation, and attention. Neuron 46:681-692

### Pattern Separation / Neurogenesis
- Leutgeb JK et al. (2007) Pattern separation in the dentate gyrus and CA3. Science 315:961-966
- Yassa MA, Stark CEL (2011) Pattern separation in the hippocampus. TINS 34:515-525
- Cognitive Neurodynamics (2025) Dynamic impact of adult neurogenesis on DG pattern separation

### Schema Theory
- Tse D et al. (2007) Schemas and memory consolidation. Science 316:76-82
- van Kesteren MTR et al. (2012) How schema and novelty augment memory formation. TINS 35:211-219
- Gilboa A, Marlatte H (2017) Neurobiology of schemas and schema-mediated memory. TICS 21:618-631

### Astrocytes / Tripartite Synapse
- Perea G et al. (2009) Tripartite synapses. TINS 32:421-431
- De Pitta M et al. (2012) Computational quest for understanding the role of astrocyte signaling. Front Comp Neurosci 6:98
- Cells/MDPI (2025) Astrocyte-mediated plasticity: multi-scale mechanisms

### Interference & Orthogonalization
- Anderson MC, Neely JH (1996) Interference and inhibition in memory retrieval
- Wixted JT (2004) The psychology and neuroscience of forgetting. Annu Rev Psychol 55:235-269
- bioRxiv (2025) Memory consolidation with orthogonal gradients

### Dendritic Computation
- Kastellakis G et al. (2015) Synaptic clustering within dendrites. Neuron 87:1144-1158
- Limbacher T, Legenstein R (2020) Emergence of stable synaptic clusters. Front Comp Neurosci 14:57
- PRX Life (2024) Impact of dendritic nonlinearities on computational capabilities

### Homeostatic Plasticity
- Turrigiano GG (2008) The self-tuning neuron: synaptic scaling. Cell 135:422-435
- Abraham WC, Bear MF (1996) Metaplasticity. TINS 19:126-130

### Memory Consolidation Systems
- McClelland JL et al. (1995) Why there are complementary learning systems. Psych Rev 102:419-457
- Kumaran D et al. (2016) What learning systems do intelligent agents need? Neuron 92:1258-1273
- Kandel ER (2001) The molecular biology of memory storage. Nobel Lecture
- Dudai Y (2012) The restless engram. Annu Rev Neurosci 35:227-247

### Engram Biology
- Josselyn SA, Tonegawa S (2020) Memory engrams: recalling the past and imagining the future. Science 367:eaaw4325
- Rashid AJ et al. (2016) Competition between engrams influences fear memory. Neuron 92:627-638

---

## Success Criteria

### For Cortex as a memory system:
1. Memories encoded during "encoding phase" survive 2x longer than random-phase encoding
2. Schema-consistent memories consolidate 3x faster than schema-inconsistent
3. Pattern separation reduces interference by >50% for similar memories
4. Replay sequences correlate with improved next-day retrieval
5. Homeostatic plasticity prevents heat distribution from collapsing to bimodal (all hot or all cold)

### For Cortex as a research tool:
1. Ablation studies produce interpretable, non-obvious results
2. Hypothesis generator produces at least one non-trivial prediction per 100 memories
3. Simulation mode can predict consolidation outcomes with >70% accuracy
4. Emergent metrics reveal parameter sensitivity (which knobs matter most)
5. System behavior qualitatively matches known neuroscience phenomena (spacing effect, testing effect, sleep benefit, schema acceleration)
