# Genius Agent Index — Route by Problem Shape

The orchestrator selects genius agents by **problem shape**, not by field or historical person. Each shape is a trigger pattern — a recognizable structure in the problem that activates a specific reasoning procedure. A single agent may serve multiple shapes; a single problem may invoke multiple agents in sequence (see "Pairs well with" in each agent's frontmatter).

> **Rule:** if no shape below matches the problem, do not force a genius agent. Use a standard team agent instead.

---

## Shape → Agent Lookup

### Measurement, Signal, and Isolation

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **residual-with-a-carrier** | measured > predicted from known parts, gap outside noise | [curie](curie.md) | Chase the excess; isolate by enrichment with control substitution |
| **instrument-before-hypothesis** | "we want to improve X" but no instrument reads X | [curie](curie.md) | Fix the instrument and its unit before deciding what to look for |
| **name-the-anomaly** | quantifiable deviation observed, no term for it yet | [curie](curie.md) | Coin a name and operational definition; forbid mechanism talk |
| **two-independent-methods** | a result from one method only | [curie](curie.md) | Require a second independent confirmation before claiming |
| **observer-effect-audit** | measurement may perturb the system (test leakage, Heisenbugs, observability overhead) | [curie](curie.md) | Audit back-action before trusting any measurement |

### Estimation and Bounding

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **order-of-magnitude-first** | decision blocked by "we don't have data" | [fermi](fermi.md) | Decompose into bracketable factors; multiply bounds |
| **bracket-before-solve** | false precision masking bad assumptions | [fermi](fermi.md) | Produce a two-sided bound + dominant uncertainty |
| **refuse-false-precision** | single-number estimate presented without bracket | [fermi](fermi.md) | Convert to bracket; name the dominant factor |
| **sanity-check** | a claimed number that nobody has cross-checked | [fermi](fermi.md) | Two independent decompositions must agree to ×10 |
| **feasibility-bound** | "is this even possible?" before committing resources | [fermi](fermi.md) | Bracket the quantity; if the high end is below viability, kill it early |

### Hard Real-Time and Failure Design

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **hard-real-time** | system must meet deadlines under overload | [hamilton](hamilton.md) | Priority-displaced scheduling by criticality |
| **priority-under-failure** | "what happens when everything goes wrong simultaneously?" | [hamilton](hamilton.md) | Shed by criticality, not by arrival order |
| **graceful-degradation** | default failure mode is crash, not degrade | [hamilton](hamilton.md) | Design the degraded state as a first-class behavior |
| **asynchronous-first** | design assumes synchronous behavior by default | [hamilton](hamilton.md) | Rewrite every "and then X happens" as "when X arrives (if ever)" |
| **defensive-by-default** | "users will never…" or "our clients always…" | [hamilton](hamilton.md) | Reverse the assumption; software handles the wrong input |

### Defining the Right Measure

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **define-the-measure-first** | "improving X" where X has no formal definition | [shannon](shannon.md) | Axiomatize the quantity; derive from properties |
| **limit-before-method** | someone proposes a method without knowing the theoretical limit | [shannon](shannon.md) | Derive the limit; compare current state; decide if method is worth it |
| **source-channel-code-separation** | layers are tangled (data, transport, processing) | [shannon](shannon.md) | Separate into independently-analyzable layers |
| **operational-definition** | a "metric" without a repeatable measurement procedure | [shannon](shannon.md) | Tie the quantity to a limit of a repeatable process |
| **noise-as-parameter** | plan starts with "eliminate the noise" | [shannon](shannon.md) | Characterize the noise; design around it |

### Distributed Systems and Formal Correctness

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **distributed-causality** | design uses wall-clock time for correctness | [lamport](lamport.md) | Replace "when" with happens-before |
| **proof-before-code** | non-trivial concurrent/distributed code with no written spec | [lamport](lamport.md) | Write the spec; model-check on small instances |
| **invariants-not-traces** | correctness argued by walking through example executions | [lamport](lamport.md) | State the invariant; prove by induction over transitions |
| **spec-first** | team debates behavior by telling stories instead of checking invariants | [lamport](lamport.md) | Write the spec as a predicate; the code refines it |
| **partial-failure-default** | design assumes messages arrive, services respond, disks don't fail | [lamport](lamport.md) | Assume every external interaction can fail in three phases |

### Long-Horizon Observation

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **long-horizon-observation** | phenomenon unfolds over weeks/months/years; snapshots will mislead | [darwin](darwin.md) | Start the notebook; match cadence to the phenomenon's timescale |
| **variation-as-data** | variation is being averaged away instead of examined | [darwin](darwin.md) | Look at the distribution, the outliers, the tails |
| **difficulty-book** | theory has no catalog of its own contradicting evidence | [darwin](darwin.md) | Open a difficulty book on day one; every contradiction goes in |
| **hardest-case-first** | theory being defended on its easiest cases | [darwin](darwin.md) | Name the hardest case; address it explicitly before shipping |
| **delay-vs-avoidance** | team delaying past readiness without a stopping rule | [darwin](darwin.md) | Set a forcing function tied to the difficulty book, not to "more confidence" |

### Symmetry and Invariance

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **symmetry-first** | problem feels intractable in direct form; hidden regularity suspected | [noether](noether.md) | Find the invariance group; quotient before solving |
| **invariance-to-conservation** | a quantity is conserved but nobody knows why | [noether](noether.md) | Find the symmetry that yields it (first theorem) |
| **find-the-group** | system has equivalences nobody has written down | [noether](noether.md) | Enumerate the symmetry group explicitly |
| **equivalence-reduction** | search space contains redundant configurations | [noether](noether.md) | Quotient by the symmetry group to shrink the space |
| **gauge-vs-global** | "conservation law" claimed from a symmetry — but is it really? | [noether](noether.md) | Classify: global → conservation; local/gauge → identity, not conservation |
| **symmetry-breaking-as-signal** | an expected symmetry is violated | [noether](noether.md) | The breaking is data; localize it to find the perturbation |

### Predictive Taxonomy

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **tabulate-and-predict-gaps** | many known items, suspected hidden regularity | [mendeleev](mendeleev.md) | Find the right axes; leave explicit gaps; predict gap properties |
| **organize-by-hidden-axis** | classification feels "almost there" with unnamed holes | [mendeleev](mendeleev.md) | Try multiple axis pairs; pick the one that maximizes gap visibility |
| **falsifiable-taxonomy** | taxonomy presented with no predictions | [mendeleev](mendeleev.md) | List what the taxonomy predicts; defend axes by predictions |
| **fill-the-empty-cell** | a gap in a matrix is suspected to be a real missing item | [mendeleev](mendeleev.md) | Predict the gap's properties from neighbors before looking for it |
| **reorder-when-prediction-fails** | a table prediction fails and an ad-hoc exception is proposed | [mendeleev](mendeleev.md) | Diagnose: mismeasurement, wrong axis, or new phenomenon |

### Understanding and Integrity

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **rederive-from-scratch** | a result is being cited without the ability to reproduce its derivation | [feynman](feynman.md) | Close the book; rederive from premises; note where you fail |
| **explain-to-freshman** | jargon used without the ability to define it in simpler terms | [feynman](feynman.md) | Explain without jargon; the failure points are understanding gaps |
| **cargo-cult-detector** | procedure followed because "successful people do it" without knowing why | [feynman](feynman.md) | Require the causal mechanism; no mechanism = cargo cult candidate |
| **integrity-audit** | a result is suspiciously clean; self-deception possible | [feynman](feynman.md) | List what could invalidate the result; the hardest items go in the report |
| **sum-over-histories** | committed to first plausible explanation without alternatives | [feynman](feynman.md) | Enumerate alternatives; the answer is where multiple lines converge |

### Single-Specimen and Anomaly

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **anomaly-others-discarded** | a class of observations is being trimmed, filtered, or labeled noise | [mcclintock](mcclintock.md) | Investigate the discarded class; the anomaly may be the phenomenon |
| **single-specimen-deep-observation** | aggregate metric smooth but specific case weird | [mcclintock](mcclintock.md) | Pick one instance; observe deeply; do not aggregate |
| **trust-direct-over-aggregate** | direct observation contradicts aggregate statistic | [mcclintock](mcclintock.md) | Investigate the disagreement; do not default to trusting the aggregate |
| **rejected-but-correct** | finding will be unfashionable for years | [mcclintock](mcclintock.md) | Publish, wait, do not retract, do not escalate beyond evidence |
| **perceptual-expertise** | vague "something is off" from someone experienced | [mcclintock](mcclintock.md) | Ground the feeling in a specific observation before acting or dismissing |

### Program Correctness and Discipline

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **proof-and-program-together** | correctness-critical code with no derivation from spec | [dijkstra](dijkstra.md) | Develop code and correctness argument hand-in-hand |
| **locality-of-reasoning** | a construct defeats understanding from surrounding context | [dijkstra](dijkstra.md) | Restrict to constructs that admit local reasoning |
| **separation-of-concerns** | one function/module addresses multiple concerns | [dijkstra](dijkstra.md) | Identify concerns; split into independently-reasonable pieces |
| **elegance-as-correctness** | code is ugly, invariant hard to state, reader struggles | [dijkstra](dijkstra.md) | Refactor until invariant and correctness are both visible |
| **tests-insufficient** | team leaning on tests for code whose failure modes tests can't cover | [dijkstra](dijkstra.md) | Name the uncovered mode; recommend the appropriate stronger discipline |

### Abstraction and Tool Design

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **compile-as-abstraction-barrier** | users forced to think in implementation vocabulary | [hopper](hopper.md) | Build a translator so users stay in domain language |
| **debugging-as-first-class** | debugging treated as shameful or under-invested | [hopper](hopper.md) | Elevate debugging: tools, vocabulary, logging, culture |
| **make-abstract-tangible** | decisions on quantities nobody can feel | [hopper](hopper.md) | Create a tangible representation the decision-maker can perceive |
| **anticipate-obsolescence** | defending a tool out of familiarity, not merit | [hopper](hopper.md) | Evaluate honestly; lead the transition |
| **ask-forgiveness-not-permission** | valuable move blocked by process (with bounded risk, demonstrable benefit) | [hopper](hopper.md) | Build first, legitimize after — but only with all four preconditions met |

### Augmentation and Human Capability

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **augment-not-automate** | default framing is "automate this" when "augment the person" is ignored | [engelbart](engelbart.md) | Ask what the human uniquely contributes; amplify that |
| **bootstrap-your-own-tools** | team building a tool doesn't use it themselves | [engelbart](engelbart.md) | Restructure so the tool is the team's daily working environment |
| **h-lam-t-system** | tool designed without attention to language, methodology, training | [engelbart](engelbart.md) | Inventory all five H-LAM/T components; design together |
| **demo-as-argument** | arguing by slide deck when a live demo is feasible | [engelbart](engelbart.md) | Build the demo; let it carry the argument |
| **raise-the-ceiling** | design entirely optimized for novice onboarding, no expert capability growth | [engelbart](engelbart.md) | Ask what experts can do after a month, a year; design for both floor and ceiling |
| **co-evolve-tool-and-practice** | assuming existing work practice won't change when tool is introduced | [engelbart](engelbart.md) | Treat tool and practice as a single coupled design object |

### Rapid Hypothesis Generation (PROVER REQUIRED)

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **conjecture-generator** | need many candidate patterns quickly in a formal domain | [ramanujan](ramanujan.md) | Compute special cases; state conjectures; **hand off to prover** |
| **pattern-from-special-cases** | analytical approach too slow; computed examples likely to reveal structure | [ramanujan](ramanujan.md) | Compute 50+ specific instances; spot the pattern |
| **notation-driven-discovery** | stuck in one notation; pattern may be visible in another | [ramanujan](ramanujan.md) | Rewrite in multiple forms until identities emerge |
| **intuition-plus-prover** | strong pattern intuition available but rigorous checking is slow | [ramanujan](ramanujan.md) | Generate at high rate; paired prover verifies each |
| **deferred-rigor-with-mandatory-handoff** | speed of generation is valuable but correctness must not be assumed | [ramanujan](ramanujan.md) | Label everything as conjecture; **NEVER ship without prover verification** |

---

## Quick Reference: Agent → Shapes

| Agent | Shapes |
|---|---|
| [curie](curie.md) | residual-with-a-carrier, instrument-before-hypothesis, name-the-anomaly, two-independent-methods, observer-effect-audit |
| [fermi](fermi.md) | order-of-magnitude-first, bracket-before-solve, refuse-false-precision, sanity-check, feasibility-bound |
| [hamilton](hamilton.md) | hard-real-time, priority-under-failure, graceful-degradation, asynchronous-first, defensive-by-default |
| [shannon](shannon.md) | define-the-measure-first, limit-before-method, source-channel-code-separation, operational-definition, noise-as-parameter |
| [lamport](lamport.md) | distributed-causality, proof-before-code, invariants-not-traces, spec-first, partial-failure-default |
| [darwin](darwin.md) | long-horizon-observation, variation-as-data, difficulty-book, hardest-case-first, delay-vs-avoidance |
| [noether](noether.md) | symmetry-first, invariance-to-conservation, find-the-group, equivalence-reduction, gauge-vs-global, symmetry-breaking-as-signal |
| [mendeleev](mendeleev.md) | tabulate-and-predict-gaps, organize-by-hidden-axis, falsifiable-taxonomy, fill-the-empty-cell, reorder-when-prediction-fails |
| [feynman](feynman.md) | rederive-from-scratch, explain-to-freshman, cargo-cult-detector, integrity-audit, sum-over-histories |
| [mcclintock](mcclintock.md) | anomaly-others-discarded, single-specimen-deep-observation, trust-direct-over-aggregate, rejected-but-correct, perceptual-expertise |
| [dijkstra](dijkstra.md) | proof-and-program-together, locality-of-reasoning, separation-of-concerns, elegance-as-correctness, tests-insufficient |
| [hopper](hopper.md) | compile-as-abstraction-barrier, debugging-as-first-class, make-abstract-tangible, anticipate-obsolescence, ask-forgiveness-not-permission |
| [engelbart](engelbart.md) | augment-not-automate, bootstrap-your-own-tools, h-lam-t-system, demo-as-argument, raise-the-ceiling, co-evolve-tool-and-practice |
| [ramanujan](ramanujan.md) | conjecture-generator, pattern-from-special-cases, notation-driven-discovery, intuition-plus-prover, deferred-rigor-with-mandatory-handoff |

---

## Common Pairings

| Situation | Agent sequence |
|---|---|
| Anomaly found → isolate → explain | mcclintock → curie → shannon or noether |
| Estimate → measure → formalize | fermi → curie → shannon |
| Conjecture → prove → implement | ramanujan → dijkstra or lamport → engineer |
| Design under failure → specify → implement | hamilton → lamport → engineer |
| Slow phenomenon → formalize → predict gaps | darwin → shannon → mendeleev |
| Integrity audit of a result | feynman (+ curie for re-measurement) |
| New tool design | engelbart (augmentation frame) → hopper (abstraction layer) → dijkstra (correctness) |
| Symmetry reduction → formal spec | noether → lamport |
| Cargo cult detected → rederive → rebuild | feynman → dijkstra or hopper |
| Structural hypothesis from constraints | kekule (count bonds) → mendeleev (tabulate) |
| Serendipity captured → isolate → develop | fleming → mcclintock or curie → engineer |
| Matched-group anomaly → cheap intervention → institutional resistance | semmelweis → fisher (rigorous design) → feynman (integrity) |
| Runtime malleability needed | kay → liskov (contracts) → hopper (abstraction) |
| Performance audit | knuth (profile 3%) → fermi (estimate) → curie (measure) |
| Decidability / complexity gate | turing → fermi (feasibility bound) |
| Cross-domain import | vonneumann → noether (symmetry) or shannon (measure) |
| Conservation audit → residual | lavoisier → curie (isolate carrier) |
| Experiment design → run → analyze | fisher → curie (measure) → darwin (long-horizon if needed) |
| Gedankenexperiment → operational definition → covariance | einstein → shannon (formalize) → noether (symmetry) |
| Idealize → minimal model → add corrections | galileo → fermi (estimate corrections) |
| Substitutability audit at composition boundary | liskov → dijkstra (module correctness) → lamport (distributed) |

---

### Computation and Formalization

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **reduce-to-mechanism** | problem drowning in implementation detail; nobody asked what the simplest machine is | [turing](turing.md) | Strip to the simplest abstract machine that captures the computation |
| **universality** | system needs to handle an open-ended set of cases | [turing](turing.md) | Build a universal machine (interpreter, plugin host, rule engine) |
| **decidability-first** | optimizing without checking if the general problem is solvable | [turing](turing.md) | Check complexity class before investing in a solution |
| **imitation-game** | debate stalled on a vague concept ("intelligent," "correct," "fair") | [turing](turing.md) | Define operationally by what passes a test |
| **oracle-separation** | stuck on multiple hard sub-problems at once | [turing](turing.md) | Oracle-solve one, analyze the rest; the bottleneck becomes visible |

### Cross-Domain Transfer and Game Theory

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **cross-domain-formal-transfer** | problem looks structurally similar to a solved problem in another field | [vonneumann](vonneumann.md) | Find the isomorphism; import the solution |
| **game-theoretic-decomposition** | multiple agents with conflicting objectives | [vonneumann](vonneumann.md) | Model as a game; find the equilibrium |
| **code-as-data** | system needs flexibility; programs/strategies should be first-class objects | [vonneumann](vonneumann.md) | Stored-program principle — treat behavior as data |
| **self-replication-as-design** | system must reproduce, scale, or grow | [vonneumann](vonneumann.md) | Three parts: description + constructor + copy mechanism |
| **find-the-isomorphism** | reinventing a solution that exists elsewhere under a different name | [vonneumann](vonneumann.md) | Search for the mapping; verify it holds |

### Conservation and Mass-Balance

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **mass-balance** | inputs and outputs not verified to match | [lavoisier](lavoisier.md) | Weigh everything in, weigh everything out; the residual is real |
| **conservation-accounting** | money, data, requests, energy, time "disappearing" | [lavoisier](lavoisier.md) | Enumerate all flows; balance the ledger |
| **residual-as-discovery** | the balance doesn't close | [lavoisier](lavoisier.md) | The residual is a real entity; name it and find its carrier |
| **rename-to-clarify** | terminology obscures rather than clarifies | [lavoisier](lavoisier.md) | Rename so names encode behavior, not history |
| **sealed-system-experiment** | unmeasured flows are suspected | [lavoisier](lavoisier.md) | Seal the system boundary; measure everything at the boundary |

### Experimental Design

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **randomize-to-eliminate-confounds** | causal claim from observational correlation only | [fisher](fisher.md) | Randomly assign treatments to units |
| **block-to-reduce-variance** | known source of variation inflating error | [fisher](fisher.md) | Group by the known source; apply all treatments within each group |
| **replicate-to-estimate-variance** | conclusion from a single run | [fisher](fisher.md) | Repeat; estimate the error variance |
| **factorial-design** | multiple factors varied one-at-a-time | [fisher](fisher.md) | Vary all factors simultaneously; detect interactions |
| **design-before-run** | "let's run it and see what happens" | [fisher](fisher.md) | Write the design document first; the analysis follows from the design |
| **sufficient-statistic** | data summary losing information | [fisher](fisher.md) | Use the statistic that captures all information about the parameter |

### Thought Experiment and Operational Definition

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **gedankenexperiment** | system hard to analyze from outside | [einstein](einstein.md) | Imagine yourself inside the system; what do you see? |
| **operational-definition-by-procedure** | concept defined without a measurement procedure | [einstein](einstein.md) | A concept IS the procedure that measures it |
| **demand-covariance** | rule gives different answers from different viewpoints | [einstein](einstein.md) | The form of the law must not depend on the observer |
| **equivalence-principle** | two things distinguished but empirically indistinguishable | [einstein](einstein.md) | If you can't tell the difference, there is no difference |
| **ride-the-phenomenon** | abstraction gap between observer and system | [einstein](einstein.md) | Get inside; ride the phenomenon; the internal view reveals structure |

### Idealization and Minimal Models

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **idealize-away-friction** | phenomenon obscured by secondary effects | [galileo](galileo.md) | Remove non-essential variables; study the idealized system |
| **inclined-plane-slowdown** | phenomenon too fast/large/rare to observe directly | [galileo](galileo.md) | Build a slower/smaller/more-frequent analog; measure that |
| **quantitative-over-qualitative** | qualitative claims without measurement | [galileo](galileo.md) | Put a number on it; numbers are debatable, impressions are not |
| **observation-over-authority** | authority cited instead of evidence | [galileo](galileo.md) | Trust observation; investigate the disagreement |
| **minimal-model-first** | first attempt at full complexity | [galileo](galileo.md) | Start minimal; add one variable at a time |

### Composability and Substitutability

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **substitutability-as-contract** | implementation breaks when swapped for its interface | [liskov](liskov.md) | The contract IS the interface — behavior, not just types |
| **behavioral-subtyping** | subtype rejects inputs or weakens promises | [liskov](liskov.md) | Preconditions may weaken; postconditions may strengthen; invariants preserved |
| **data-abstraction** | callers depending on internal representation | [liskov](liskov.md) | Hide representation behind operations |
| **contract-is-interface** | interface has methods but no behavioral specification | [liskov](liskov.md) | Write the contract: pre, post, invariant, history constraint |
| **composition-correctness** | system correct per-component but breaks when composed | [liskov](liskov.md) | Swap-test every implementation against the interface contract |

### Data Against Institution

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **statistical-anomaly-between-groups** | matched groups with wildly different outcomes | [semmelweis](semmelweis.md) | Compare; the unmatched variable is the candidate cause |
| **intervene-and-remeasure** | candidate cause identified; need to test | [semmelweis](semmelweis.md) | Cheapest intervention + before/after data |
| **data-against-institution** | evidence clear but organization resists | [semmelweis](semmelweis.md) | Plan the communication as carefully as the investigation |
| **cheap-intervention-test** | proposed fix is low-cost but being blocked | [semmelweis](semmelweis.md) | Implement, re-measure, present the before/after contrast |
| **semmelweis-reflex-awareness** | anticipate institutional rejection of correct evidence | [semmelweis](semmelweis.md) | Name the reflex; route around it with stakeholder-aware communication |

### Serendipity Capture

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **serendipity-capture** | anomalies appear during routine work and are being cleaned up | [fleming](fleming.md) | Investigate before discarding |
| **notice-what-others-discard** | a class of observations is routinely thrown away | [fleming](fleming.md) | Inspect the discards; the signal may be there |
| **follow-up-immediately** | "that's weird" said and nobody writes it down | [fleming](fleming.md) | Investigate NOW; the anomaly fades |
| **structured-readiness** | environment optimized to suppress surprises | [fleming](fleming.md) | Redesign to make surprises visible |
| **publish-before-application** | finding characterized but application unknown | [fleming](fleming.md) | Publish; someone else may develop it |

### Runtime Malleability

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **late-binding** | decision hardcoded that could be deferred to runtime | [kay](kay.md) | Defer; late binding gains adaptability |
| **messaging-over-procedure** | tight coupling via direct procedure calls | [kay](kay.md) | Send messages; let the receiver decide how to handle |
| **medium-is-message** | building an application when an environment would serve better | [kay](kay.md) | Design the environment, not just the application |
| **build-for-children** | "our users will know how to do this" without testing | [kay](kay.md) | Test with the hardest user; children expose every implicit assumption |
| **invent-the-future** | blocked by a missing tool | [kay](kay.md) | Estimate build cost vs wait cost; if cheaper, build it |
| **runtime-malleability** | system must be changeable by users at runtime | [kay](kay.md) | Default to late binding + messaging + user-modifiable environment |

### Performance and Code Literacy

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **profile-before-optimizing** | optimizing without profiling data | [knuth](knuth.md) | Profile; identify the 3% hot path; leave the 97% alone |
| **premature-optimization-in-context** | "premature optimization" invoked to block all optimization | [knuth](knuth.md) | Quote the full passage — the 3% MUST be optimized |
| **literate-programming** | code unreadable; "add comments" proposed as fix | [knuth](knuth.md) | Code as narrative for human reader; explain why, not just what |
| **algorithmic-analysis-first** | implementing without knowing the complexity class | [knuth](knuth.md) | Analyze Big-O before coding; wrong class = no amount of optimization saves it |
| **build-the-tool-use-the-tool** | tool built but not used to produce its own artifacts | [knuth](knuth.md) | Use it; the gaps become visible (recursive validation) |

### Structural Hypothesis from Constraints

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **structural-hypothesis-from-constraints** | components with known connection properties; structure unknown | [kekule](kekule.md) | Count the bonds; let the count force the shape |
| **valence-counting** | connections available vs required don't match | [kekule](kekule.md) | The deficit/surplus constrains the topology |
| **shape-from-bonding** | "what shape fits these constraints?" | [kekule](kekule.md) | Enumerate candidate topologies; check against behavioral constraints |
| **spatial-analogical-reasoning** | known structure with similar constraint profile exists | [kekule](kekule.md) | Import the structure if constraints match |
| **distinguish-method-from-narrative** | discovery explained by "insight" narrative instead of method | [kekule](kekule.md) | Check primary sources for the actual procedure; the narrative is probably embellished |

---

## Quick Reference: Agent → Shapes (complete, 26 agents)

| Agent | Shapes |
|---|---|
| [curie](curie.md) | residual-with-a-carrier, instrument-before-hypothesis, name-the-anomaly, two-independent-methods, observer-effect-audit |
| [fermi](fermi.md) | order-of-magnitude-first, bracket-before-solve, refuse-false-precision, sanity-check, feasibility-bound |
| [hamilton](hamilton.md) | hard-real-time, priority-under-failure, graceful-degradation, asynchronous-first, defensive-by-default |
| [shannon](shannon.md) | define-the-measure-first, limit-before-method, source-channel-code-separation, operational-definition, noise-as-parameter |
| [lamport](lamport.md) | distributed-causality, proof-before-code, invariants-not-traces, spec-first, partial-failure-default |
| [darwin](darwin.md) | long-horizon-observation, variation-as-data, difficulty-book, hardest-case-first, delay-vs-avoidance |
| [noether](noether.md) | symmetry-first, invariance-to-conservation, find-the-group, equivalence-reduction, gauge-vs-global, symmetry-breaking-as-signal |
| [mendeleev](mendeleev.md) | tabulate-and-predict-gaps, organize-by-hidden-axis, falsifiable-taxonomy, fill-the-empty-cell, reorder-when-prediction-fails |
| [feynman](feynman.md) | rederive-from-scratch, explain-to-freshman, cargo-cult-detector, integrity-audit, sum-over-histories |
| [mcclintock](mcclintock.md) | anomaly-others-discarded, single-specimen-deep-observation, trust-direct-over-aggregate, rejected-but-correct, perceptual-expertise |
| [dijkstra](dijkstra.md) | proof-and-program-together, locality-of-reasoning, separation-of-concerns, elegance-as-correctness, tests-insufficient |
| [hopper](hopper.md) | compile-as-abstraction-barrier, debugging-as-first-class, make-abstract-tangible, anticipate-obsolescence, ask-forgiveness-not-permission |
| [engelbart](engelbart.md) | augment-not-automate, bootstrap-your-own-tools, h-lam-t-system, demo-as-argument, raise-the-ceiling, co-evolve-tool-and-practice |
| [ramanujan](ramanujan.md) | conjecture-generator, pattern-from-special-cases, notation-driven-discovery, intuition-plus-prover, deferred-rigor-with-mandatory-handoff |
| [turing](turing.md) | reduce-to-mechanism, universality, decidability-first, imitation-game, oracle-separation |
| [vonneumann](vonneumann.md) | cross-domain-formal-transfer, game-theoretic-decomposition, code-as-data, self-replication-as-design, find-the-isomorphism |
| [lavoisier](lavoisier.md) | mass-balance, conservation-accounting, residual-as-discovery, rename-to-clarify, sealed-system-experiment |
| [fisher](fisher.md) | randomize-to-eliminate-confounds, block-to-reduce-variance, replicate-to-estimate-variance, factorial-design, design-before-run, sufficient-statistic |
| [einstein](einstein.md) | gedankenexperiment, operational-definition-by-procedure, demand-covariance, equivalence-principle, ride-the-phenomenon |
| [galileo](galileo.md) | idealize-away-friction, inclined-plane-slowdown, quantitative-over-qualitative, observation-over-authority, minimal-model-first |
| [liskov](liskov.md) | substitutability-as-contract, behavioral-subtyping, data-abstraction, contract-is-interface, composition-correctness |
| [semmelweis](semmelweis.md) | statistical-anomaly-between-groups, intervene-and-remeasure, data-against-institution, cheap-intervention-test, semmelweis-reflex-awareness |
| [fleming](fleming.md) | serendipity-capture, notice-what-others-discard, follow-up-immediately, structured-readiness, publish-before-application |
| [kay](kay.md) | late-binding, messaging-over-procedure, medium-is-message, build-for-children, invent-the-future, runtime-malleability |
| [knuth](knuth.md) | profile-before-optimizing, premature-optimization-in-context, literate-programming, algorithmic-analysis-first, build-the-tool-use-the-tool |
| [kekule](kekule.md) | structural-hypothesis-from-constraints, valence-counting, shape-from-bonding, spatial-analogical-reasoning, distinguish-method-from-narrative |

---

## Evaluated and Rejected (no distinct primary-source-backed shape)

| Candidate | Closest existing coverage | Reason for rejection |
|---|---|---|
| Hawking | von Neumann (cross-domain transfer) | "Regime-boundary collision" is real but overlaps von Neumann; procedure reconstructed from math, not explicitly stated |
| Tesla | Einstein (gedankenexperiment) | Mental simulation overlaps Einstein; *My Inventions* is a retrospective autobiography, not a methodology document |
| Jobs | Engelbart + Hopper + Feynman | No primary-source methodology documents; keynotes are performances, not procedures |
| Gray | Shannon (source-channel-code) | Harmonic telegraph subsumed by Shannon; telautograph insight is interesting but thin and not explicitly articulated |
