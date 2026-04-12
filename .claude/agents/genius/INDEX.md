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
| [varela](varela.md) | mutual-constraint-triangulation, first-person-as-data, observer-inside-system, trained-phenomenological-observation, neurophenomenology, second-person-bridge |
| [ekman](ekman.md) | anchor-subjective-to-anatomical, micro-temporal-leakage, baseline-deviation-as-signal, cross-cultural-calibration, objective-coding-of-subjective-domain, affective-signal-detection |
| [alkhwarizmi](alkhwarizmi.md) | reduce-to-canonical-form, classify-all-cases, normalize-before-solve, systematic-transformation, exhaustive-case-enumeration |
| [thompson](thompson.md) | scale-break-analysis, surface-to-volume-audit, form-follows-scale, transformation-grid, allometric-scaling |
| [zhuangzi](zhuangzi.md) | question-the-metric, usefulness-of-uselessness, evaluation-framework-audit, perspective-multiplication, goodhart-detector |
| [bateson](bateson.md) | schismogenesis-detection, double-bind-diagnosis, meta-communication-audit, logical-type-confusion, pattern-that-connects |
| [coase](coase.md) | transaction-cost-boundary, build-vs-buy-analysis, boundary-optimization, make-or-market, coordination-cost-accounting |
| [godel](godel.md) | self-reference-limit, incompleteness-detection, consistency-vs-completeness, system-cannot-verify-itself, godel-sentence-construction |
| [midgley](midgley.md) | metaphor-audit, conceptual-plumbing, hidden-analogy-detection, metaphor-breakdown-point, discipline-imperialism-check |
| [leguin](leguin.md) | ambiguous-utopia, force-genuine-tradeoff, carrier-bag-narrative, live-with-the-design, narrative-frame-audit |
| [wu](wu.md) | error-archaeology, test-the-obvious, precision-as-refutation, assumption-inventory, untested-assumption-detection |

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
| Causal claim → isolate → test | pearl → fisher → curie |
| Stuck on problem → heuristics → test | polya → peirce → fisher |
| Decision under bias → debias → verify | kahneman → popper → feynman |
| System misbehavior → diagnose → intervene | meadows → beer → deming |
| Design trade-off → resolve contradiction → implement | altshuller → engineer |
| Unknown system → reverse engineer (type known) | rejewski → ventris |
| Unknown system → reverse engineer (type unknown) | champollion → ventris |
| Unknown system → reverse engineer (no parallel) | ventris (standalone) |
| Recurring design problem → extract pattern → compose | alexander → dijkstra |
| False binary → dissolve → reframe | nagarjuna → wittgenstein |
| Language confusion → audit → clarify | wittgenstein → aristotle (persuasion) |
| Antifragility assessment → stress test → redesign | taleb → hamilton → kauffman |
| Multi-timescale analysis → structural cause | braudel → meadows → darwin |
| Forensic trace analysis → deep investigation | ginzburg → mcclintock → peirce |
| Formal specification of domain → compress | panini → knuth → shannon |
| Combinatorial space → tractability check → reduce | borges → turing → noether |
| Possibility space exploration → feasibility | lem → fermi |
| Merger/symbiosis hypothesis → conservation check | margulis → lavoisier |
| Commons governance → institutional design | ostrom → beer |
| Organizational lifecycle → structural plausibility | ibnkhaldun → fermi |
| Adversarial tempo → priority under failure | boyd → hamilton |
| Heuristic discovery → rigorous proof | archimedes → dijkstra or lamport |
| Systematic doubt → fresh investigation | ibnalhaytham → galileo → curie |
| Thoughtlessness diagnosis → process redesign | arendt → deming |
| Notation blocking progress → redesign | euler → panini |
| Problem in many forms → normalize → solve | alkhwarizmi → knuth (analyze) → engineer |
| System changing scale → predict breaks → redesign | thompson → fermi (estimate) → alexander (redesign) |
| Metric gaming / Goodhart's Law → audit framework | zhuangzi → midgley (hidden metaphor) → meadows (system archetype) |
| Teams in runaway escalation → diagnose → intervene | bateson → meadows (system trap) → ostrom (governance) |
| Boundary decision → cost analysis → optimize | coase → simon (satisficing) → liskov (contracts) |
| System auditing itself → limits check → external verification | godel → turing (decidability) → popper (falsifiability) |
| Hidden metaphor shaping decisions → expose → reframe | midgley → wittgenstein (language game) → zhuangzi (framework audit) |
| Design with hidden costs → force trade-off naming → live-with test | leguin → kahneman (pre-mortem) → darwin (long-horizon) |
| Untested assumptions → error archaeology → precision test | wu → curie (measurement) → fisher (experiment design) |
| Capacity planning → queue model → load test | erlang → fermi (estimate arrival rate) → wu (test the assumption) |
| Feedback oscillation → stability check → tune | maxwell → meadows (system archetype) → deming (PDSA) |
| Uncertain evidence → update beliefs → calibrate | laplace → pearl (causal structure) → kahneman (bias check) |
| Onboarding design → ZPD assessment → scaffold | vygotsky → polya (problem-solving heuristics) → alexander (pattern language) |
| Stuck on approach → reflect → reframe → switch | schon → polya (find related problem) → zhuangzi (question the metric) |
| Multi-stakeholder conflict → negotiate → govern | rogerfisher → ostrom (commons governance) → aristotle (persuasion) |
| Adoption stalling → diagnose chasm → intervene | rogers → semmelweis (data against institution) → meadows (leverage point) |
| Process inefficiency → find theoretical limit → locate waste | carnot → shannon (define measure) → lavoisier (conservation audit) |
| Users can't find things → faceted classification → test | ranganathan → eco (model reader) → vygotsky (progressive disclosure) |
| Network structure → phase transition → vulnerability | erdos → mandelbrot (scale-free) → hamilton (failure design) |
| Argument construction → structure → review | toulmin → aristotle (persuasion) → feynman (integrity) |
| Literature synthesis → pool → grade | cochrane → fisher (design) → laplace (Bayesian) |
| Text interpretation → meaning → application | gadamer → wittgenstein (language) → hart (legal reasoning) |
| Cultural understanding → observe → describe | geertz → ekman (behavioral coding) → bruner (narrative) |
| Theory from data → code → saturate | strauss → peirce (abduction) → popper (falsify) |
| Outbreak investigation → trace → intervene | snow → pearl (causal graph) → fisher (experiment) |
| Diagnosis → differential → treat | feinstein → laplace (Bayesian update) → kahneman (debias) |
| Rule application → precedent → balance | hart → rawls (justice) → aristotle (four causes) |
| Cross-case comparison → necessary/sufficient | mill → mendeleev (taxonomy) → popper (falsify) |
| Discourse shapes reality → expose → reframe | foucault → midgley (hidden metaphor) → wittgenstein (dissolve) |
| Micro-rules → macro-patterns → predict | schelling → kauffman (edge-of-chaos) → meadows (leverage) |
| Narrative as data → structure → meaning | bruner → propp (sequence grammar) → geertz (thick description) |

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

### Embodied Observation and Micro-Temporal Signal

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **mutual-constraint-triangulation** | first-person report contradicts third-person measurement and the gap IS the phenomenon | [varela](varela.md) | Triangulate: neither level reduces to the other; use both under mutual constraint |
| **first-person-as-data** | self-report dismissed as "subjective" or accepted without training protocol | [varela](varela.md) | Train the observer; treat trained first-person report as data, not anecdote |
| **observer-inside-system** | standard assumption of external observer breaks down | [varela](varela.md) | Acknowledge the observer is inside; design protocols accordingly |
| **trained-phenomenological-observation** | vague subjective impression needs grounding | [varela](varela.md) | Apply neurophenomenological reduction: bracket, describe, correlate |
| **neurophenomenology** | neural/behavioral data alone misses the experiential dimension | [varela](varela.md) | Pair first-person phenomenological report with third-person measurement |
| **second-person-bridge** | first-person and third-person perspectives need mediation | [varela](varela.md) | Use second-person perspective as methodological bridge |
| **anchor-subjective-to-anatomical** | domain treated as "subjective" but could be objectified | [ekman](ekman.md) | Anchor to observable anatomical units; build a coding system |
| **micro-temporal-leakage** | signals concealed in temporal resolution below normal observation | [ekman](ekman.md) | Slow down; look at sub-second timescales for involuntary leakage |
| **baseline-deviation-as-signal** | aggregate analysis misses individual deviation | [ekman](ekman.md) | Establish baseline per subject; flag deviations as signal |
| **cross-cultural-calibration** | coding system needs calibration across contexts | [ekman](ekman.md) | Separate universal from conventional via cross-cultural validation |
| **objective-coding-of-subjective-domain** | affective/attentional state must be read from behavior | [ekman](ekman.md) | Build anatomically-grounded coding system with inter-rater reliability |
| **affective-signal-detection** | emotional state relevant but unmeasured | [ekman](ekman.md) | Apply FACS-style coding; detect what self-report misses |

### Causal and Abductive Reasoning

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **ladder-of-causation** | causal claim from observational data alone | [pearl](pearl.md) | Classify: association, intervention, or counterfactual? Escalate level as needed |
| **intervention-vs-association** | "X causes Y" claimed from correlation | [pearl](pearl.md) | Apply do-calculus; check if causal effect is identifiable from data + graph |
| **causal-graph-construction** | causal relationships unclear or implicit | [pearl](pearl.md) | Draw the DAG; make every causal assumption explicit and testable |
| **confound-detection** | controlled-for variables may introduce collider bias | [pearl](pearl.md) | Check d-separation; controlling for colliders opens backdoor paths |
| **counterfactual-reasoning** | "what would have happened if we had done X instead?" | [pearl](pearl.md) | Build structural causal model; compute counterfactual from model |
| **abductive-inference** | surprising observation demands explanation | [peirce](peirce.md) | Generate candidate hypotheses ranked by explanatory power |
| **inquiry-cycle** | investigation stuck or incomplete | [peirce](peirce.md) | Run the full cycle: doubt → abduction → deduction → induction → belief |
| **pragmatic-maxim** | concept unclear or disputed | [peirce](peirce.md) | Define by practical consequences: "what difference would it make?" |
| **economy-of-research** | multiple hypotheses, limited budget | [peirce](peirce.md) | Test cheapest-to-refute hypothesis first |
| **belief-fixation-diagnosis** | team stuck on a belief for the wrong reason | [peirce](peirce.md) | Diagnose fixation method: tenacity, authority, a priori, or inquiry? |

### Systematic Invention and Problem-Solving

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **contradiction-formulation** | improving one parameter degrades another | [altshuller](altshuller.md) | Formulate as technical or physical contradiction; resolve, don't compromise |
| **inventive-principles** | trade-off seems inescapable | [altshuller](altshuller.md) | Apply the 40 inventive principles indexed by contradiction type |
| **ideal-final-result** | complex solution proposed for a simple need | [altshuller](altshuller.md) | Imagine the ideal: the function is achieved, the mechanism disappears |
| **evolution-pattern** | system at an evolutionary plateau | [altshuller](altshuller.md) | Identify the evolution pattern; predict the next stage |
| **resources-in-zone** | solution requires new resources | [altshuller](altshuller.md) | Inventory resources already present in the zone before adding new ones |
| **understand-before-solving** | jumping to solution without understanding the problem | [polya](polya.md) | Restate the problem; identify the unknown, the data, the conditions |
| **work-backward** | goal clear but path unknown | [polya](polya.md) | Start from the desired result; work backward to the starting conditions |
| **find-related-problem** | problem seems novel | [polya](polya.md) | Search for a related solved problem; adapt its method |
| **specialize-then-generalize** | general case intractable | [polya](polya.md) | Solve special cases; look for the pattern; then generalize |
| **look-back-and-generalize** | problem solved but the solution is ad-hoc | [polya](polya.md) | Review the solution; extract the general method; check by different method |

### Decision-Making and Cognitive Bias

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **system-1-system-2-audit** | high-stakes decision made on fast intuition | [kahneman](kahneman.md) | Flag System 1; engage System 2; check for substitution |
| **pre-mortem** | plan with no failure scenarios | [kahneman](kahneman.md) | Imagine it failed; work backward to find what went wrong |
| **reference-class-forecasting** | estimate suspiciously precise or optimistic | [kahneman](kahneman.md) | Find the reference class; use its base rate as anchor |
| **substitution-detection** | easier question answered instead of the hard one | [kahneman](kahneman.md) | Identify the substitution; answer the actual question |
| **framing-neutralization** | same decision framed differently would yield different choice | [kahneman](kahneman.md) | Reframe from multiple angles; decide on the version-invariant answer |
| **fragility-classification** | system not evaluated for response to disorder | [taleb](taleb.md) | Classify: fragile (harmed by volatility), robust (indifferent), antifragile (benefits) |
| **via-negativa** | improvement by addition is the default | [taleb](taleb.md) | Improve by subtraction; remove what harms before adding what helps |
| **barbell-strategy** | moderate-risk strategy that fails in extremes | [taleb](taleb.md) | Combine extremely safe + extremely speculative; eliminate the fragile middle |
| **optionality-design** | commitment required under uncertainty | [taleb](taleb.md) | Design for optionality: small downside, unlimited upside |
| **skin-in-the-game** | decision-makers shielded from consequences | [taleb](taleb.md) | Require skin in the game; no asymmetric risk transfer |
| **falsifiability-gate** | claim presented as testable but no test would refute it | [popper](popper.md) | Demand: what observation would prove this wrong? No answer = not testable |
| **severity-of-test** | easy confirmations masquerading as evidence | [popper](popper.md) | Design the severe test: the one most likely to fail if the hypothesis is wrong |
| **conjectures-and-refutations** | hypothesis accepted without attempted refutation | [popper](popper.md) | Conjecture boldly; refute rigorously; eliminate errors |
| **piecemeal-over-utopian** | plan too large to test incrementally | [popper](popper.md) | Break into testable pieces; implement and test piecemeal |
| **demarcation-check** | boundary between science and pseudoscience (or engineering and wishful thinking) unclear | [popper](popper.md) | Apply falsifiability criterion; classify claims accordingly |

### Systems Thinking and Leverage

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **leverage-point-ranking** | many possible interventions, unclear where to focus | [meadows](meadows.md) | Rank by Meadows' 12 leverage points; intervene at the highest accessible level |
| **system-archetype** | recurring pattern (shifting the burden, escalation, tragedy of commons) | [meadows](meadows.md) | Identify the archetype; apply the known structural remedy |
| **stock-flow-delay** | system behavior confusing due to accumulations and delays | [meadows](meadows.md) | Map stocks, flows, and delays; behavior follows from structure |
| **feedback-dominance-shift** | system behaves differently at different scales or times | [meadows](meadows.md) | Identify which feedback loop dominates in each regime |
| **paradigm-transcendence** | the system's goals and rules are themselves the problem | [meadows](meadows.md) | Transcend the paradigm; change the goal, not the parameters |
| **viable-system-diagnosis** | system fails despite local fixes | [beer](beer.md) | Audit against VSM: are all five systems present and connected? |
| **variety-engineering** | system overwhelmed by environmental complexity | [beer](beer.md) | Match internal variety to environmental variety; attenuate or amplify as needed |
| **recursive-viability** | viability required at multiple nested levels | [beer](beer.md) | Each viable subsystem must itself contain all five systems |
| **five-system-audit** | organizational dysfunction with unclear structural cause | [beer](beer.md) | Check Systems 1-5; the missing or broken system is the diagnosis |
| **autonomy-cohesion-balance** | subsystem autonomy vs whole-system cohesion in tension | [beer](beer.md) | Design the balance: maximum autonomy compatible with cohesion |
| **edge-of-chaos-tuning** | system too rigid or too chaotic | [kauffman](kauffman.md) | Tune connectivity toward the phase transition; neither frozen nor chaotic |
| **adjacent-possible** | need innovation without breaking what works | [kauffman](kauffman.md) | Explore the adjacent possible: one step from current state |
| **fitness-landscape-navigation** | hill-climbing trapped in local optimum | [kauffman](kauffman.md) | Map the NK landscape; use the right search strategy for its ruggedness |
| **order-for-free** | order appears without anyone imposing it | [kauffman](kauffman.md) | Recognize order from network topology; don't impose what emerges free |
| **work-constraint-cycle** | energy/work flows unclear | [kauffman](kauffman.md) | Trace the work-constraint cycle; identify where the cycle breaks |
| **common-vs-special-cause** | persistent quality problems blamed on individuals | [deming](deming.md) | Diagnose: common cause (system) or special cause (event)? Treat accordingly |
| **pdsa-cycle** | improvement without prediction or reflection | [deming](deming.md) | Plan-Do-Study-Act with explicit prediction at the Plan stage |
| **system-appreciation** | component optimized without understanding the whole | [deming](deming.md) | Appreciate the system; sub-optimization harms the whole |
| **drive-out-fear** | fear suppresses honest reporting | [deming](deming.md) | Drive out fear; restore signal flow; people must be safe to report truth |
| **cease-dependence-on-inspection** | "more testing" proposed as quality fix | [deming](deming.md) | Build quality in at the source; cease dependence on inspection |

### Design Patterns and Wholeness

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **pattern-language-composition** | recurring design problems solved differently each time | [alexander](alexander.md) | Name the pattern; compose patterns into a language |
| **generative-sequence** | design feels dead or mechanical | [alexander](alexander.md) | Apply the generative sequence; each step increases wholeness |
| **wholeness-diagnostic** | design has structural integrity issues | [alexander](alexander.md) | Evaluate against the fifteen fundamental properties |
| **decomposition-by-misfit** | decomposing by components instead of by what can go wrong | [alexander](alexander.md) | Decompose by misfit variables; the partition reveals natural modules |
| **fifteen-properties** | evaluating design quality | [alexander](alexander.md) | Check the fifteen properties; absence indicates structural weakness |
| **function-extraction** | sequential process needs structural analysis | [propp](propp.md) | Extract typed atomic functions from the sequence |
| **sequence-constraint** | process instances vary — what is invariant? | [propp](propp.md) | Identify the fixed sequence constraints across instances |
| **role-abstraction** | same function performed by different actors | [propp](propp.md) | Abstract the role from the actor; the function is what matters |
| **gap-detection-via-grammar** | possible gaps in a process | [propp](propp.md) | Apply the morphological grammar; gaps become visible |
| **morphological-comparison** | comparing process variants | [propp](propp.md) | Align by function, not by surface form; structural comparison |

### Commons, Governance, and Institutions

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **eight-design-principles** | shared resource at risk of degradation | [ostrom](ostrom.md) | Audit against Ostrom's eight principles; patch the missing ones |
| **polycentric-governance** | centralized control infeasible or undesirable | [ostrom](ostrom.md) | Design polycentric governance; multiple overlapping authorities |
| **iad-framework** | institutional rules need systematic analysis | [ostrom](ostrom.md) | Apply the IAD framework: action arena, rules, physical conditions, community |
| **rules-in-use-vs-on-paper** | formal rules diverge from actual behavior | [ostrom](ostrom.md) | Audit rules-in-use vs rules-on-paper; the gap is the diagnosis |
| **commons-sustainability** | "how do we prevent tragedy of the commons?" | [ostrom](ostrom.md) | Apply the eight principles; neither privatize nor centralize |
| **thoughtlessness-audit** | systemic harm from suppressed judgment, not malice | [arendt](arendt.md) | Diagnose: is thinking itself being eliminated by the system? |
| **labor-work-action** | activities need classification by what they produce | [arendt](arendt.md) | Classify: labor (cyclical maintenance), work (durable artifact), action (new beginning) |
| **cog-in-machine-detection** | "I was just following the process" | [arendt](arendt.md) | Diagnose the systemic design that suppresses individual judgment |
| **thinking-as-dialogue** | system has no space for thinking | [arendt](arendt.md) | Create space for thinking: the silent dialogue of the mind with itself |
| **vita-activa** | system reduces everything to one type of activity | [arendt](arendt.md) | Ensure the full range: labor, work, and action all have their place |
| **structural-plausibility-filter** | authoritative claim that may be structurally impossible | [ibnkhaldun](ibnkhaldun.md) | Test against material constraints before evaluating the source |
| **cohesion-lifecycle** | team/company/movement rising or declining | [ibnkhaldun](ibnkhaldun.md) | Model the asabiyyah lifecycle; identify current phase |
| **peripheral-displaces-center** | scrappy challenger vs established incumbent | [ibnkhaldun](ibnkhaldun.md) | Check peripheral cohesion vs center complacency; the periphery may win |
| **causality-based-verification** | narrative needs testing against four causes | [ibnkhaldun](ibnkhaldun.md) | Verify against material, formal, efficient, final causes |
| **confirmation-bias-detection** | analysis may be distorted by existing beliefs | [ibnkhaldun](ibnkhaldun.md) | Check for confirmation bias before accepting the analysis |

### Reverse Engineering and Decipherment

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **black-box-reconstruction** | system internals unknown but I/O observable | [rejewski](rejewski.md) | Reconstruct the hidden structure from input-output behavior |
| **structural-invariant-matching** | need to identify unknown configuration | [rejewski](rejewski.md) | Extract structural invariants; match against a catalog |
| **exploit-procedure-not-algorithm** | the algorithm is strong but the deployment is weak | [rejewski](rejewski.md) | Attack the procedure, not the algorithm |
| **crib-anchored-constraint-solving** | known fragments anchor an underdetermined system | [rejewski](rejewski.md) | Use cribs to reduce the search space |
| **catalog-and-match** | many configurations possible; need lookup | [rejewski](rejewski.md) | Pre-compute structural signatures; use catalog for lookup |
| **bilingual-bootstrapping** | unknown system with a parallel known system | [champollion](champollion.md) | Use the known system as Rosetta Stone; bootstrap from correspondences |
| **anchor-and-propagate** | partial mapping established; need to extend | [champollion](champollion.md) | Anchor at known points; propagate constraints outward |
| **counting-disproof** | dominant theory can be disproved by counting | [champollion](champollion.md) | Count distinct elements; if count disproves the theory, the theory is wrong |
| **dual-nature-recognition** | system resists classification as type A or type B | [champollion](champollion.md) | It may be both; recognize dual nature |
| **living-descendant-decoder** | a "living descendant" of the dead system exists | [champollion](champollion.md) | Use the living descendant to decode the dead system |
| **grid-constraint-propagation** | unknown system; structure must be inferred from patterns | [ventris](ventris.md) | Build a grid; propagate constraints; let structure emerge |
| **assumption-free-structure** | assumptions about the system's nature may be wrong | [ventris](ventris.md) | Extract structure without semantic assumptions |
| **inflection-as-structure-revealer** | variations in form may reveal structural categories | [ventris](ventris.md) | Use inflectional patterns to classify elements |
| **speculative-decoupling** | interpretation attempt too tightly coupled to analysis | [ventris](ventris.md) | Decouple structural analysis from semantic hypothesis |
| **test-by-prediction** | candidate interpretation needs validation | [ventris](ventris.md) | Generate predictions from the interpretation; check against unseen data |

### Qualitative Dynamics and Scale

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **qualitative-before-quantitative** | problem resists direct computation but qualitative behavior is analyzable | [poincare](poincare.md) | Understand stability, periodicity, convergence before solving exactly |
| **structured-incubation** | brute-force search failing; creative insight needed | [poincare](poincare.md) | Conscious preparation → deliberate incubation → sudden illumination → verification |
| **topological-equivalence** | two problems may be the same in disguise | [poincare](poincare.md) | Check if they are topologically equivalent; solving one solves both |
| **convention-detection** | constraint assumed to be a law but may be a convention | [poincare](poincare.md) | Distinguish genuine constraint from arbitrary convention |
| **structural-stability** | small parameter change may cause qualitative shift | [poincare](poincare.md) | Check for bifurcation points; classify the stability |
| **scale-free-pattern** | irregularity that has structure | [mandelbrot](mandelbrot.md) | Check for self-similarity across scales |
| **roughness-as-parameter** | smoothness assumed but irregularity dominates | [mandelbrot](mandelbrot.md) | Measure the roughness; treat it as a parameter, not noise |
| **self-similarity** | same pattern appears at different scales | [mandelbrot](mandelbrot.md) | Confirm self-similarity; use it for prediction and analysis |
| **fat-tail-detection** | extreme events more frequent than Gaussian predicts | [mandelbrot](mandelbrot.md) | Test for power-law tails; if present, averages and standard deviations are misleading |
| **mild-vs-wild-randomness** | risk model assumes bounded variation | [mandelbrot](mandelbrot.md) | Classify: mild (Gaussian, bounded) or wild (power-law, unbounded extremes) |

### Beyond-Binary and Linguistic Analysis

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **tetralemma** | debate stuck on a false dichotomy | [nagarjuna](nagarjuna.md) | Check all four: P, not-P, both, neither |
| **fourfold-negation** | question itself may be malformed | [nagarjuna](nagarjuna.md) | Reject the question if all four positions fail |
| **emptiness-of-essence** | concept treated as having inherent, context-independent existence | [nagarjuna](nagarjuna.md) | Show it depends on context; no intrinsic nature |
| **dependent-origination** | entity assumed to be self-standing | [nagarjuna](nagarjuna.md) | Trace the conditioning relations; everything arises in dependence |
| **prasanga-reductio** | opponent's position needs internal refutation | [nagarjuna](nagarjuna.md) | Show the position collapses under its own assumptions |
| **language-game-audit** | team stuck in debate that never resolves | [wittgenstein](wittgenstein.md) | Check if different language games are being played; align the rules |
| **dissolve-dont-solve** | problem seems profound but may be a linguistic confusion | [wittgenstein](wittgenstein.md) | Dissolve the pseudo-problem; the confusion was in the framing |
| **meaning-as-use** | word means different things to different people | [wittgenstein](wittgenstein.md) | Meaning is use in context; check how each party actually uses the term |
| **family-resemblance** | category has no common essence | [wittgenstein](wittgenstein.md) | Accept family resemblance; don't force a definition where none exists |
| **show-dont-say** | attempting to state what can only be shown | [wittgenstein](wittgenstein.md) | Show it in use; don't try to capture it in a definition |
| **four-causes-interrogation** | explanation incomplete | [aristotle](aristotle.md) | Ask: material, formal, efficient, final cause? |
| **fallacy-catalog** | argument may contain hidden fallacy | [aristotle](aristotle.md) | Check against the fallacy catalog |
| **division-by-differentiae** | domain needs systematic taxonomy | [aristotle](aristotle.md) | Divide by differentiae: genus + distinguishing feature |
| **knowing-that-vs-knowing-why** | team knows that something works but not why | [aristotle](aristotle.md) | Push from knowing-that to knowing-why; depth of understanding |
| **persuasion-architecture** | proposal needs to persuade a specific audience | [aristotle](aristotle.md) | Structure argument: ethos, logos, pathos for the audience |
| **generative-specification** | system needs compact rules generating all valid outputs | [panini](panini.md) | Build a generative grammar: all valid forms, no invalid ones |
| **rule-conflict-resolution** | rules conflict with each other | [panini](panini.md) | Apply meta-rules for resolution; more specific overrides more general |
| **compression-by-metalanguage** | specification is bloated | [panini](panini.md) | Compress using metalanguage: rules about rules |
| **auxiliary-markers** | metadata must be embedded in the specification | [panini](panini.md) | Use auxiliary markers: compile-time metadata stripped at output |
| **economy-principle** | rule set may be redundant | [panini](panini.md) | Minimize: fewest rules that cover the domain |

### Temporal and Forensic Analysis

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **three-timescale-decomposition** | firefighting events without seeing structural cause | [braudel](braudel.md) | Decompose into structure (longue duree), conjuncture (cycle), event |
| **structure-over-event** | decision driven by latest event | [braudel](braudel.md) | Find the structural factor; it explains more than the event |
| **system-as-geography** | system treated as a timeline | [braudel](braudel.md) | Treat it as geography: spatial, structural, persistent constraints |
| **multi-causal-layering** | single-cause explanation proposed | [braudel](braudel.md) | Every phenomenon has causes at all three timescales |
| **longue-duree-priority** | short-term metrics obscure long-term trends | [braudel](braudel.md) | Look for the slow-moving constraints first |
| **marginal-detail-as-signature** | official account doesn't match observed behavior | [ginzburg](ginzburg.md) | Read the marginal details the source didn't intend to reveal |
| **involuntary-evidence** | deliberate testimony may be unreliable | [ginzburg](ginzburg.md) | Prefer involuntary evidence over deliberate testimony |
| **trace-to-structure** | peripheral detail may expose hidden pattern | [ginzburg](ginzburg.md) | Follow the trace to the structure it reveals |
| **read-against-the-grain** | system conceals its actual mechanism | [ginzburg](ginzburg.md) | Read against the grain; find what the system hides |
| **single-anomalous-case** | aggregate data hides individual structure | [ginzburg](ginzburg.md) | Investigate a single anomalous case deeply; it may expose the pattern |

### Possibility Space and Combinatorics

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **exhaustive-space-audit** | system claims completeness | [borges](borges.md) | Audit: is the space actually searchable? Is completeness meaningful? |
| **map-territory-discipline** | abstraction confused with the thing it represents | [borges](borges.md) | Separate the map from the territory; the map is not the territory |
| **self-reference-detection** | system describes or contains itself | [borges](borges.md) | Check for paradoxes from self-reference |
| **forking-paths-analysis** | decision tree with unexplored branches | [borges](borges.md) | Enumerate all forks; the unexplored branches may matter most |
| **context-as-meaning** | "the same thing" means different things in different contexts | [borges](borges.md) | Meaning depends on context; identical text, different meaning |
| **possibility-space-exploration** | standard forecast too narrow | [lem](lem.md) | Map the full possibility space; include what lies beyond current categories |
| **push-to-logical-extreme** | design needs stress-testing | [lem](lem.md) | Push every principle to its logical extreme; see what breaks |
| **unknowable-system-audit** | system may be beyond current conceptual categories | [lem](lem.md) | Acknowledge the Solaris problem: some systems resist all existing frameworks |
| **review-of-nonexistent** | design space clarified better by what should exist but doesn't | [lem](lem.md) | Describe the nonexistent; it illuminates the design space |
| **evolution-as-design-analogy** | evolutionary and cybernetic analogies would illuminate trade-offs | [lem](lem.md) | Apply evolutionary analogy: variation, selection, retention, but for technology |

### Symbiosis and Cooperation

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **merger-not-competition** | "competition" assumed but cooperation may be the mechanism | [margulis](margulis.md) | Check for merger: formerly independent entities fused |
| **serial-endosymbiosis** | system components have independent lifecycle indicators | [margulis](margulis.md) | Check for endosymbiotic origin: own replication, own structure |
| **convergent-evidence-requirement** | non-obvious origin story needs multi-line proof | [margulis](margulis.md) | Build convergent evidence from independent lines |
| **formerly-independent-entity** | component with suspicious autonomy | [margulis](margulis.md) | Check if it was formerly independent; independent origin explains the autonomy |
| **persistence-against-rejection** | finding will be rejected by orthodoxy | [margulis](margulis.md) | Persist with evidence; don't retract under social pressure |

### Discovery Methods

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **heuristic-then-proof** | need to find the answer first, prove it later | [archimedes](archimedes.md) | Use mechanical/physical method to discover; then prove rigorously |
| **cross-domain-discovery** | abstract problem may have physical analog | [archimedes](archimedes.md) | Map to physical system; the physical answer suggests the abstract one |
| **method-of-exhaustion** | exact answer needed via bounding | [archimedes](archimedes.md) | Bound from above and below; converge to the answer |
| **physical-modeling-as-discovery** | analytical methods too slow | [archimedes](archimedes.md) | Build a physical (or simulated) model; read the answer off |
| **know-result-first** | the hard part is knowing WHAT to prove | [archimedes](archimedes.md) | Find the result by any means; then construct the proof |
| **notation-as-infrastructure** | current notation obscures the solution | [euler](euler.md) | Redesign notation so the solution becomes visible |
| **systematic-exhaustive-enumeration** | question settleable by enumerating all structural cases | [euler](euler.md) | Enumerate all cases systematically; leave none unchecked |
| **abstraction-by-deletion** | irrelevant detail hides essential structure | [euler](euler.md) | Delete what doesn't matter; the essential structure remains |
| **productive-generalization** | specific result can be generalized | [euler](euler.md) | Generalize from specific to family; the family reveals deeper structure |
| **identity-discovery** | unexpected equality connecting unrelated domains | [euler](euler.md) | Search for identities; connections between domains are the deepest results |

### Adversarial Decision-Making

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **ooda-loop** | decision-cycle speed matters | [boyd](boyd.md) | Observe → Orient → Decide → Act faster than the adversary |
| **orientation-as-synthesis** | stale or incorrect mental model | [boyd](boyd.md) | Orientation is the critical bottleneck; rebuild the synthesis |
| **destructive-deduction** | old paradigm blocking progress | [boyd](boyd.md) | Break the old model into pieces; recombine into new synthesis |
| **fast-transients** | need to disorient competitor or escape a trap | [boyd](boyd.md) | Rapid state changes; the adversary cannot keep up |
| **schwerpunkt** | limited resources, must concentrate | [boyd](boyd.md) | Maximum energy at the decisive point; everything else supports |

### Interpretation and Semiotics

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **model-reader-construction** | artifact misinterpreted by its audience | [eco](eco.md) | Design for the Model Reader; anticipate their competencies |
| **open-vs-closed-design** | artifact should permit multiple or single valid uses | [eco](eco.md) | Classify: open (multiple valid interpretations) or closed (single path) |
| **limits-of-interpretation** | readings projected onto artifact that its structure doesn't support | [eco](eco.md) | Apply the limits; the artifact constrains valid interpretations |
| **semiotic-gap-analysis** | communication failure between producer and consumer | [eco](eco.md) | Diagnose the semiotic gap; where does encoding diverge from decoding? |
| **abductive-detection-cycle** | working from incomplete evidence | [eco](eco.md) | Generate abductive hypotheses; test against the artifact's structure |

### Systematic Doubt

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **systematic-doubt-document** | predecessor theory accepted on authority | [ibnalhaytham](ibnalhaytham.md) | Document every claim of the predecessor theory; test each one |
| **controlled-variable-isolation** | experiment requires isolating variables | [ibnalhaytham](ibnalhaytham.md) | Isolate one variable; control all others; measure |
| **mathematical-formalization** | qualitative observations need mathematical treatment | [ibnalhaytham](ibnalhaytham.md) | Formalize the observation mathematically; precision enables refutation |
| **reproducibility-by-design** | reproducibility is an afterthought | [ibnalhaytham](ibnalhaytham.md) | Design for reproducibility from the start; document procedure completely |
| **falsifiability-as-criterion** | claim not structured for falsification | [ibnalhaytham](ibnalhaytham.md) | Restructure the claim so it can be falsified; then attempt falsification |

### Bounded Rationality and Satisficing

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **satisficing** | "find the optimal solution" blocking progress | [simon](simon.md) | Set a satisficing threshold; accept the first solution that meets it |
| **near-decomposability** | complex system needs modular decomposition | [simon](simon.md) | Test for near-decomposability: strong intra-module, weak inter-module interactions |
| **means-ends-analysis** | gap between current and goal state | [simon](simon.md) | Identify the difference; find the operator that reduces it |
| **design-as-search** | solution space too large for exhaustive analysis | [simon](simon.md) | Treat design as heuristic search; navigate the space with bounded rationality |
| **hierarchy-as-default** | no organizing principle for complex system | [simon](simon.md) | Hierarchy is the default architecture for complexity; start there |

### Canonical Form and Algorithmic Specification

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **reduce-to-canonical-form** | problem appears in many superficially different forms | [alkhwarizmi](alkhwarizmi.md) | Apply systematic transformations to reduce to standard solvable form |
| **classify-all-cases** | solution needed for a family of problems, not just one | [alkhwarizmi](alkhwarizmi.md) | Enumerate all possible forms; provide algorithm for each |
| **normalize-before-solve** | irregular input needs standardization before processing | [alkhwarizmi](alkhwarizmi.md) | Normalize first; solve the normalized form |
| **exhaustive-case-enumeration** | "are we sure we've covered all cases?" | [alkhwarizmi](alkhwarizmi.md) | Enumerate exhaustively; prove completeness |

### Scale and Physical Constraint

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **scale-break-analysis** | system growing/shrinking and assumptions may not hold | [thompson](thompson.md) | What breaks when size changes? Surface scales as square, volume as cube |
| **surface-to-volume-audit** | communication/coordination costs growing faster than team/system size | [thompson](thompson.md) | Audit the surface-to-volume ratio; it constrains what's possible at each scale |
| **form-follows-scale** | scaling up by replication instead of redesign | [thompson](thompson.md) | The form that works at one scale may be impossible at another |
| **allometric-scaling** | non-linear relationship between size and capability | [thompson](thompson.md) | Map the scaling law; predict where current form fails |

### Evaluation Framework and Meta-Critique

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **question-the-metric** | team optimizing a metric that may be the wrong metric | [zhuangzi](zhuangzi.md) | Is this the RIGHT thing to optimize? What is destroyed by this metric? |
| **usefulness-of-uselessness** | "useless" things being discarded that might be valuable by a different standard | [zhuangzi](zhuangzi.md) | Check what escapes the evaluation framework |
| **goodhart-detector** | metric has decoupled from the thing it was supposed to measure | [zhuangzi](zhuangzi.md) | When the measure becomes the target, it ceases to be a good measure |
| **evaluation-framework-audit** | the evaluation framework itself may be the problem | [zhuangzi](zhuangzi.md) | Step outside the frame; who designed it? What does it exclude? |

### Interaction Pathology and Communication Level

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **schismogenesis-detection** | two parties in runaway escalation | [bateson](bateson.md) | Symmetrical (both mirror/amplify) or complementary (rigid role divergence)? |
| **double-bind-diagnosis** | contradictory messages at different logical levels | [bateson](bateson.md) | The bind: obeying requires disobeying; commenting on the bind violates the bind |
| **meta-communication-audit** | message and meta-message conflict | [bateson](bateson.md) | Separate content from meta-communication; find where levels are tangled |
| **logical-type-confusion** | rules about rules confused with rules | [bateson](bateson.md) | Identify the level confusion; untangle the types |

### Boundary and Transaction Cost

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **transaction-cost-boundary** | deciding what should be inside vs outside a system | [coase](coase.md) | Compare internal coordination cost vs external transaction cost |
| **build-vs-buy-analysis** | make-or-buy decision with hidden costs | [coase](coase.md) | Map ALL costs: integration, vendor risk, negotiation, maintenance |
| **boundary-optimization** | too many or too few boundaries in the system | [coase](coase.md) | Boundary should be where coordination cost equals transaction cost |

### Self-Reference and Formal Limits

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **self-reference-limit** | system trying to validate/audit/verify itself | [godel](godel.md) | Sufficiently powerful self-referential systems cannot fully verify themselves |
| **incompleteness-detection** | assuming the test suite / audit / review covers everything | [godel](godel.md) | There will be truths the system cannot prove about itself |
| **consistency-vs-completeness** | trying to have both strict rules and total coverage | [godel](godel.md) | You can have consistency OR completeness, not both; choose |

### Hidden Metaphor and Conceptual Infrastructure

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **metaphor-audit** | the vocabulary itself is shaping conclusions | [midgley](midgley.md) | What metaphor is silently doing the thinking? Find it, examine it |
| **conceptual-plumbing** | surface argument clear but something feels wrong underneath | [midgley](midgley.md) | Dig beneath to find the hidden conceptual infrastructure |
| **metaphor-breakdown-point** | a useful metaphor is being stretched past its valid range | [midgley](midgley.md) | Every metaphor breaks somewhere; find where this one breaks |
| **discipline-imperialism-check** | one domain claiming explanatory authority over all others | [midgley](midgley.md) | "Everything is just X" — is that justified? |

### Trade-Off Honesty and Narrative Frame

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **ambiguous-utopia** | everyone excited but nobody naming what will be lost | [leguin](leguin.md) | Some trade-offs are irreducible; NAME them honestly |
| **force-genuine-tradeoff** | design presented as "all upside" | [leguin](leguin.md) | What is the ACTUAL lived cost over years? |
| **carrier-bag-narrative** | project framed as hero's journey (conquer, triumph) | [leguin](leguin.md) | What if the real story is gathering, holding, containing? |
| **narrative-frame-audit** | the story the team tells about the project may be distorting decisions | [leguin](leguin.md) | What does the current narrative include and exclude? |

### Untested Assumptions and Error Archaeology

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **error-archaeology** | building on previous work without auditing its assumptions | [wu](wu.md) | Catalog errors and untested assumptions in ALL predecessor work |
| **test-the-obvious** | foundational assumption treated as too obvious to test | [wu](wu.md) | The most important tests are of things "everyone knows" to be true |
| **precision-as-refutation** | need to distinguish between competing hypotheses | [wu](wu.md) | Calibrate precision to be sufficient to distinguish null from alternative |
| **untested-assumption-detection** | system has tested behaviors but assumed others | [wu](wu.md) | Enumerate what has been TESTED vs ASSUMED; the gap is the vulnerability |

### Queuing Theory and Capacity Planning

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **arrival-service-balance** | queue growing without bound | [erlang](erlang.md) | If arrival rate ≥ service rate, no optimization helps — add capacity or shed load |
| **utilization-latency-curve** | latency spikes at high utilization | [erlang](erlang.md) | Response time = service time / (1-utilization); nonlinear hyperbola |
| **littles-law-audit** | sanity-checking queue metrics | [erlang](erlang.md) | L = λW; if any two known, third is determined |
| **queue-capacity-planning** | planning for expected load | [erlang](erlang.md) | Given target latency + arrival rate, calculate required capacity |

### Feedback Control and Stability

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **feedback-stability-analysis** | autoscaler/circuit-breaker oscillating | [maxwell](maxwell.md) | Check characteristic equation roots; negative real parts = stable |
| **gain-margin-diagnosis** | system overshoots or oscillates | [maxwell](maxwell.md) | Gain too high for the delay; reduce gain or reduce delay |
| **oscillation-detection** | sustained/growing oscillation in feedback system | [maxwell](maxwell.md) | Sustained = stability boundary; growing = unstable; damped = poorly tuned |

### Bayesian Reasoning and Calibration

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **bayesian-updating** | combining prior knowledge with new evidence | [laplace](laplace.md) | Posterior ∝ Likelihood × Prior; update incrementally |
| **prior-elicitation** | need to make assumptions explicit before seeing data | [laplace](laplace.md) | What do you believe and why? Make the prior explicit |
| **calibration-audit** | checking whether probability estimates are well-calibrated | [laplace](laplace.md) | Of things you assign 80%, do 80% happen? |

### Pedagogy and Knowledge Transfer

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **zone-of-proximal-development** | calibrating challenge to learner capability | [vygotsky](vygotsky.md) | What can they do alone? With help? The gap is where learning happens |
| **scaffolding-and-fading** | providing support that can be gradually removed | [vygotsky](vygotsky.md) | Support in the ZPD, then systematically remove as competence grows |
| **misconception-diagnosis** | learner fails despite adequate support | [vygotsky](vygotsky.md) | Is the task above ZPD? Scaffolding insufficient? Or a misconception blocks? |

### Meta-Cognitive Strategy and Reflective Practice

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **reflection-in-action** | situation responding unexpectedly during work | [schon](schon.md) | Notice surprise, reflect on what it reveals, adjust approach |
| **reframing** | stuck despite repeated attempts with current approach | [schon](schon.md) | Change the problem frame, not just the solution |
| **strategy-switching** | diminishing returns from current approach | [schon](schon.md) | Detect the signals; switch agent/method rather than pushing harder |

### Negotiation and Multi-Stakeholder Coordination

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **interests-vs-positions** | parties making demands without stating underlying needs | [rogerfisher](rogerfisher.md) | Separate what they DEMAND from what they NEED |
| **batna-analysis** | need to know walkaway point before negotiating | [rogerfisher](rogerfisher.md) | What is each party's best alternative if negotiation fails? |
| **zone-of-possible-agreement** | determining whether a deal is possible | [rogerfisher](rogerfisher.md) | Find where acceptable ranges overlap |

### Diffusion and Adoption

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **adoption-curve-segmentation** | adoption stalling, need to understand why | [rogers](rogers.md) | Map adopters into 5 categories; each needs different messaging |
| **chasm-diagnosis** | adoption stops after enthusiasts but before mainstream | [rogers](rogers.md) | Early adopters buy on vision; early majority buy on references and ROI |
| **innovation-attributes** | predicting whether an innovation will be adopted | [rogers](rogers.md) | Audit: relative advantage, compatibility, complexity, trialability, observability |

### Thermodynamic Efficiency

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **efficiency-limit-derivation** | need to know theoretical maximum before optimizing | [carnot](carnot.md) | Derive the hard ceiling; compare actual to ideal |
| **reversibility-audit** | finding where irreversible losses occur in a process | [carnot](carnot.md) | Each irreversible step produces entropy; locate the biggest producers |
| **entropy-production-localization** | process inefficient but unclear where waste occurs | [carnot](carnot.md) | Map entropy production per step; biggest producers = highest-priority targets |

### Information Architecture and Findability

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **faceted-classification** | items locked in single hierarchy when users need multiple access paths | [ranganathan](ranganathan.md) | Decompose into independent facets; retrieve by any combination |
| **five-laws-of-findability** | users can't find what they need | [ranganathan](ranganathan.md) | Every item its user, every user their item, save the user's time |
| **information-scent-optimization** | users getting lost in navigation | [ranganathan](ranganathan.md) | At every decision point, can the user smell whether the target is down this path? |

### Probabilistic Method and Graph Structure

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **probabilistic-existence-proof** | need to prove a solution exists without constructing it | [erdos](erdos.md) | Show random construction succeeds with probability > 0 |
| **random-graph-threshold** | need to know at what density a network property appears | [erdos](erdos.md) | Phase transitions: below threshold = fragmented; above = giant component |
| **extremal-combinatorics** | what is the minimum structure that guarantees a property? | [erdos](erdos.md) | How many edges/tests/connections guarantee the desired property? |

### Argumentation and Research Paper Structure

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **claim-evidence-warrant** | argument presented without visible logical structure; "why should I believe this?" | [toulmin](toulmin.md) | Identify claim, data, and warrant; if any is missing, the argument is incomplete |
| **qualifier-and-rebuttal** | unqualified claim with no failure conditions stated | [toulmin](toulmin.md) | Demand the qualifier (how strong?) and the rebuttal (when does it fail?) |
| **backing-the-warrant** | inference rule offered as self-evident without justification | [toulmin](toulmin.md) | Ask what backs the warrant; an ungrounded warrant is an empty inference |
| **argument-mapping** | complex argument with tangled reasoning that needs visualization | [toulmin](toulmin.md) | Map the six-part structure visually; connections and gaps become visible |
| **field-dependent-standards** | standards of evidence from one field applied uncritically to another | [toulmin](toulmin.md) | Standards are field-dependent; identify what counts as evidence in THIS field |

### Evidence Synthesis and Meta-Analysis

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **systematic-review-protocol** | about to review evidence without pre-specified question or inclusion criteria | [cochrane](cochrane.md) | Write the protocol BEFORE seeing results; prevent post-hoc criteria adjustment |
| **effect-size-extraction** | comparing results across studies that use different metrics or scales | [cochrane](cochrane.md) | Standardize to a common effect size before pooling or comparing |
| **heterogeneity-detection** | pooled result from multiple sources; sources may not agree | [cochrane](cochrane.md) | Test I² and prediction intervals; if heterogeneity is high, the average is misleading |
| **publication-bias-audit** | published evidence may overestimate the true effect | [cochrane](cochrane.md) | Apply funnel plots and Egger's test; the missing studies change the conclusion |
| **evidence-grading** | evidence cited without assessing its quality or level | [cochrane](cochrane.md) | Grade by hierarchy: systematic reviews > RCTs > cohort > case series > opinion |

### Hermeneutics and Textual Interpretation

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **hermeneutic-circle** | stuck understanding something complex in one pass | [gadamer](gadamer.md) | Iterate: form hypothesis about whole, examine parts, revise, repeat until coherence |
| **horizon-fusion** | interpreter claiming pure objectivity or projecting assumptions unchecked | [gadamer](gadamer.md) | Fuse the text's horizon with the interpreter's; neither alone produces understanding |
| **pre-understanding-audit** | about to interpret something important without examining own assumptions | [gadamer](gadamer.md) | Write down what you expect BEFORE reading; put pre-understandings at risk |
| **explanation-vs-understanding** | wrong mode applied — explaining when understanding is needed, or vice versa | [gadamer](gadamer.md) | Know which mode applies: causal explanation (natural science) vs interpretive understanding (human science) |
| **principle-of-charity** | interpretation assumes the worst about the text or speaker | [gadamer](gadamer.md) | Interpret charitably first; assume the text is coherent until proven otherwise |

### Ethnography and Thick Description

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **thick-description** | description captures behavior but not its meaning to the actors | [geertz](geertz.md) | Add the meaning-structure: not just what happened but what it MEANT |
| **emic-vs-etic** | phenomenon described entirely in the observer's categories | [geertz](geertz.md) | Learn insider categories first; layer analytical categories on top, not instead |
| **participant-observation** | description based on pure observation without access to meaning | [geertz](geertz.md) | Oscillate between participating (access meaning) and observing (maintain analytical distance) |
| **cultural-interpretation** | behavior treated as self-explanatory when it carries cultural significance | [geertz](geertz.md) | Read the behavior as a text embedded in webs of significance |
| **reflexivity-in-fieldwork** | observer's presence and categories shaping what they see, unacknowledged | [geertz](geertz.md) | Account for the observer's position; intellectual honesty demands reflexivity |

### Grounded Theory and Qualitative Research

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **open-coding** | about to apply a pre-existing framework to qualitative data | [strauss](strauss.md) | Code the data line by line first; let categories emerge rather than imposing them |
| **constant-comparison** | list of codes/labels without systematic comparison | [strauss](strauss.md) | Compare each new code to all previous codes; group into categories by properties and dimensions |
| **theoretical-sampling** | sampling driven by convenience rather than by emerging theory | [strauss](strauss.md) | Sample where the categories need development; the theory drives data collection |
| **axial-coding** | categories identified but relationships between them unclear | [strauss](strauss.md) | Relate categories via conditions, actions, and consequences; build the relational structure |
| **theoretical-saturation** | no stopping rule for data collection | [strauss](strauss.md) | Stop when new data adds nothing new to the categories; saturation is the stopping rule |

### Epidemiological Reasoning and Population Spread

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **outbreak-investigation** | something spreading through a population and nobody has mapped it | [snow](snow.md) | Define cases, map them in space and time, identify the exposure, remove the source |
| **hills-criteria** | causal claim from observational data; association vs causation unclear | [snow](snow.md) | Apply Hill's nine criteria: strength, consistency, specificity, temporality, gradient, plausibility, coherence, experiment, analogy |
| **epidemic-curve-analysis** | spreading phenomenon not yet plotted over time | [snow](snow.md) | Plot new cases by time unit; the shape reveals the source type (point, propagated, continuous) |
| **attack-rate-calculation** | suspected exposure but no comparison between exposed and unexposed | [snow](snow.md) | Calculate attack rates in exposed vs unexposed; the relative risk quantifies the association |
| **case-definition** | investigation proceeding without a precise definition of what counts as a case | [snow](snow.md) | Operationally define a case BEFORE counting; any two investigators must agree on classification |

### Clinical and Diagnostic Reasoning

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **differential-diagnosis** | single hypothesis for a diagnostic problem; anchoring on first match | [feinstein](feinstein.md) | Generate a ranked differential of plausible causes; include a "must not miss" |
| **likelihood-ratio-updating** | evidence gathered but not assessed for how much it shifts probability | [feinstein](feinstein.md) | Assign likelihood ratios; evidence that doesn't discriminate between candidates is noise |
| **treatment-threshold** | gathering more evidence without defining when to act | [feinstein](feinstein.md) | Define test and treatment thresholds; act when probability crosses the point where expected benefit exceeds expected harm |
| **evidence-based-practice** | decision based on authority or tradition rather than graded evidence | [feinstein](feinstein.md) | Apply the evidence hierarchy; ground decisions in the best available evidence at the appropriate level |
| **clinical-judgment-audit** | implicit diagnostic reasoning that needs to be made explicit and auditable | [feinstein](feinstein.md) | Make the Bayesian reasoning explicit; implicit updating is unteachable and error-prone |

### Legal Reasoning and Rule Application

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **open-texture-analysis** | applying a rule as if it clearly determines the answer when the case is in the penumbra | [hart](hart.md) | Identify whether the case is in the rule's core (clear) or penumbra (judgment needed) |
| **reasoning-by-precedent** | decision in the penumbra without looking for prior analogous decisions | [hart](hart.md) | Find the most relevant precedent; extract its ratio decidendi; apply or distinguish |
| **rule-exception-structure** | applying a rule without mapping its exceptions and their conditions | [hart](hart.md) | Map the full rule-exception hierarchy before applying; neither over-rigid nor over-flexible |
| **proportionality-balancing** | competing rules or principles in conflict with no method for resolution | [hart](hart.md) | Assess suitability, necessity, and proportionality stricto sensu; balance transparently |
| **ratio-decidendi** | past decision cited without extracting the governing principle | [hart](hart.md) | Extract the principle that governed the decision, not the incidental details (obiter dicta) |

### Comparative Case Method

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **method-of-agreement** | multiple positive cases; need to find what they share | [mill](mill.md) | Check which conditions are present in ALL positive cases; those are necessary-condition candidates |
| **method-of-difference** | two similar cases with different outcomes; need to isolate the cause | [mill](mill.md) | Find where they differ; the smallest set of differences contains the candidate cause |
| **qualitative-comparative-analysis** | many cases, many conditions, answer is probably configurational | [mill](mill.md) | Build truth table; apply Boolean minimization; find minimal sufficient configurations |
| **necessary-vs-sufficient** | causal claim conflating necessary and sufficient conditions | [mill](mill.md) | Distinguish: necessary (present in all positive cases) vs sufficient (its presence guarantees the outcome) |
| **most-similar-most-different** | need to select comparison cases but selection is ad hoc | [mill](mill.md) | Select most-similar cases to isolate the differing factor, or most-different to find the common factor |

### Discourse Analysis and Power/Knowledge

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **genealogy-of-practice** | practice treated as natural or inevitable; "we've always done it this way" | [foucault](foucault.md) | Trace the contingent historical origins; expose that it could have been otherwise |
| **discourse-formation-analysis** | certain things unsayable in the organization; nobody asks why | [foucault](foucault.md) | Map the rules governing what can be said, by whom, and what is systematically excluded |
| **power-knowledge-nexus** | knowledge claim presented as neutral when institutional interests produced it | [foucault](foucault.md) | Ask who produced this knowledge, who funded it, who benefits, what it crowds out |
| **archaeology-of-assumptions** | current practice rests on unstated rules nobody has examined | [foucault](foucault.md) | Excavate the episteme: the unstated rules beneath current categories and practices |
| **subject-position-mapping** | categories shaping the people who inhabit them | [foucault](foucault.md) | Map how categories (senior/junior, user/admin) constitute the subjects who occupy them |

### Emergence and Micro-to-Macro

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **micro-to-macro-inference** | collective outcome assumed to reflect collective intention | [schelling](schelling.md) | Identify individual-level rules; simulate aggregation; the macro pattern may be unintended |
| **tipping-point-detection** | "things were fine, then suddenly everything broke" | [schelling](schelling.md) | Find the threshold where gradual change produces sudden phase transition; that is the leverage point |
| **focal-point-coordination** | agents coordinating without communication on a shared default | [schelling](schelling.md) | Identify the focal point — the salient, not optimal, choice that "everyone knows everyone knows" |
| **unintended-aggregate-consequences** | mild individual preferences producing extreme collective outcome | [schelling](schelling.md) | Trace how individually reasonable behavior aggregates into irrational collective result |
| **agent-based-reasoning** | macro pattern not deducible from micro rules by inspection alone | [schelling](schelling.md) | Simulate: run the micro rules; observe what emerges; do not assume the macro resembles the micro |

### Narrative Reasoning

| Shape | Trigger | Agent | Key move |
|---|---|---|---|
| **narrative-vs-paradigmatic** | analysis logically complete but feels like it is missing something | [bruner](bruner.md) | Check if the question is narrative (what happened, what it meant) and the analysis is paradigmatic; switch modes |
| **story-as-sensemaking** | someone telling a story about events and the story is being dismissed as noise | [bruner](bruner.md) | Analyze the story AS data: what is included, excluded, emphasized? The story IS their understanding |
| **narrative-structure-analysis** | need to understand why people acted as they did | [bruner](bruner.md) | Apply Burke's pentad: agent, act, scene, agency, purpose; find where the pentad breaks down |
| **canonical-breach-detection** | something unexpected happened and people are trying to make sense of it | [bruner](bruner.md) | Identify the breach — the disruption of the canonical script; meaning is generated at the disruption point |
| **identity-through-narrative** | organizational or individual identity unclear or in flux | [bruner](bruner.md) | Identity is constituted by the stories told; change the story to change the identity |

---

## Quick Reference: Agent → Shapes (complete, 97 agents)

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
| [varela](varela.md) | mutual-constraint-triangulation, first-person-as-data, observer-inside-system, trained-phenomenological-observation, neurophenomenology, second-person-bridge |
| [ekman](ekman.md) | anchor-subjective-to-anatomical, micro-temporal-leakage, baseline-deviation-as-signal, cross-cultural-calibration, objective-coding-of-subjective-domain, affective-signal-detection |
| [pearl](pearl.md) | ladder-of-causation, intervention-vs-association, causal-graph-construction, confound-detection, counterfactual-reasoning |
| [peirce](peirce.md) | abductive-inference, inquiry-cycle, pragmatic-maxim, economy-of-research, belief-fixation-diagnosis |
| [altshuller](altshuller.md) | contradiction-formulation, inventive-principles, ideal-final-result, evolution-pattern, resources-in-zone |
| [polya](polya.md) | understand-before-solving, work-backward, find-related-problem, specialize-then-generalize, look-back-and-generalize |
| [kahneman](kahneman.md) | system-1-system-2-audit, pre-mortem, reference-class-forecasting, substitution-detection, framing-neutralization |
| [taleb](taleb.md) | fragility-classification, via-negativa, barbell-strategy, optionality-design, skin-in-the-game |
| [popper](popper.md) | falsifiability-gate, severity-of-test, conjectures-and-refutations, piecemeal-over-utopian, demarcation-check |
| [meadows](meadows.md) | leverage-point-ranking, system-archetype, stock-flow-delay, feedback-dominance-shift, paradigm-transcendence |
| [beer](beer.md) | viable-system-diagnosis, variety-engineering, recursive-viability, five-system-audit, autonomy-cohesion-balance |
| [kauffman](kauffman.md) | edge-of-chaos-tuning, adjacent-possible, fitness-landscape-navigation, order-for-free, work-constraint-cycle |
| [deming](deming.md) | common-vs-special-cause, pdsa-cycle, system-appreciation, drive-out-fear, cease-dependence-on-inspection |
| [alexander](alexander.md) | pattern-language-composition, generative-sequence, wholeness-diagnostic, decomposition-by-misfit, fifteen-properties |
| [propp](propp.md) | function-extraction, sequence-constraint, role-abstraction, gap-detection-via-grammar, morphological-comparison |
| [ostrom](ostrom.md) | eight-design-principles, polycentric-governance, iad-framework, rules-in-use-vs-on-paper, commons-sustainability |
| [arendt](arendt.md) | thoughtlessness-audit, labor-work-action, cog-in-machine-detection, thinking-as-dialogue, vita-activa |
| [ibnkhaldun](ibnkhaldun.md) | structural-plausibility-filter, cohesion-lifecycle, peripheral-displaces-center, causality-based-verification, confirmation-bias-detection |
| [rejewski](rejewski.md) | black-box-reconstruction, structural-invariant-matching, exploit-procedure-not-algorithm, crib-anchored-constraint-solving, catalog-and-match |
| [champollion](champollion.md) | bilingual-bootstrapping, anchor-and-propagate, counting-disproof, dual-nature-recognition, living-descendant-decoder |
| [ventris](ventris.md) | grid-constraint-propagation, assumption-free-structure, inflection-as-structure-revealer, speculative-decoupling, test-by-prediction |
| [poincare](poincare.md) | qualitative-before-quantitative, structured-incubation, topological-equivalence, convention-detection, structural-stability |
| [mandelbrot](mandelbrot.md) | scale-free-pattern, roughness-as-parameter, self-similarity, fat-tail-detection, mild-vs-wild-randomness |
| [nagarjuna](nagarjuna.md) | tetralemma, fourfold-negation, emptiness-of-essence, dependent-origination, prasanga-reductio |
| [wittgenstein](wittgenstein.md) | language-game-audit, dissolve-dont-solve, meaning-as-use, family-resemblance, show-dont-say |
| [aristotle](aristotle.md) | four-causes-interrogation, fallacy-catalog, division-by-differentiae, knowing-that-vs-knowing-why, persuasion-architecture |
| [panini](panini.md) | generative-specification, rule-conflict-resolution, compression-by-metalanguage, auxiliary-markers, economy-principle |
| [braudel](braudel.md) | three-timescale-decomposition, structure-over-event, system-as-geography, multi-causal-layering, longue-duree-priority |
| [ginzburg](ginzburg.md) | marginal-detail-as-signature, involuntary-evidence, trace-to-structure, read-against-the-grain, single-anomalous-case |
| [borges](borges.md) | exhaustive-space-audit, map-territory-discipline, self-reference-detection, forking-paths-analysis, context-as-meaning |
| [lem](lem.md) | possibility-space-exploration, push-to-logical-extreme, unknowable-system-audit, review-of-nonexistent, evolution-as-design-analogy |
| [margulis](margulis.md) | merger-not-competition, serial-endosymbiosis, convergent-evidence-requirement, formerly-independent-entity, persistence-against-rejection |
| [archimedes](archimedes.md) | heuristic-then-proof, cross-domain-discovery, method-of-exhaustion, physical-modeling-as-discovery, know-result-first |
| [euler](euler.md) | notation-as-infrastructure, systematic-exhaustive-enumeration, abstraction-by-deletion, productive-generalization, identity-discovery |
| [boyd](boyd.md) | ooda-loop, orientation-as-synthesis, destructive-deduction, fast-transients, schwerpunkt |
| [eco](eco.md) | model-reader-construction, open-vs-closed-design, limits-of-interpretation, semiotic-gap-analysis, abductive-detection-cycle |
| [ibnalhaytham](ibnalhaytham.md) | systematic-doubt-document, controlled-variable-isolation, mathematical-formalization, reproducibility-by-design, falsifiability-as-criterion |
| [simon](simon.md) | satisficing, near-decomposability, means-ends-analysis, design-as-search, hierarchy-as-default |
| [alkhwarizmi](alkhwarizmi.md) | reduce-to-canonical-form, classify-all-cases, normalize-before-solve, systematic-transformation, exhaustive-case-enumeration |
| [thompson](thompson.md) | scale-break-analysis, surface-to-volume-audit, form-follows-scale, transformation-grid, allometric-scaling |
| [zhuangzi](zhuangzi.md) | question-the-metric, usefulness-of-uselessness, evaluation-framework-audit, perspective-multiplication, goodhart-detector |
| [bateson](bateson.md) | schismogenesis-detection, double-bind-diagnosis, meta-communication-audit, logical-type-confusion, pattern-that-connects |
| [coase](coase.md) | transaction-cost-boundary, build-vs-buy-analysis, boundary-optimization, make-or-market, coordination-cost-accounting |
| [godel](godel.md) | self-reference-limit, incompleteness-detection, consistency-vs-completeness, system-cannot-verify-itself, godel-sentence-construction |
| [midgley](midgley.md) | metaphor-audit, conceptual-plumbing, hidden-analogy-detection, metaphor-breakdown-point, discipline-imperialism-check |
| [leguin](leguin.md) | ambiguous-utopia, force-genuine-tradeoff, carrier-bag-narrative, live-with-the-design, narrative-frame-audit |
| [wu](wu.md) | error-archaeology, test-the-obvious, precision-as-refutation, assumption-inventory, untested-assumption-detection |
| [erlang](erlang.md) | arrival-service-balance, utilization-latency-curve, littles-law-audit, queue-capacity-planning, blocking-probability |
| [maxwell](maxwell.md) | feedback-stability-analysis, governor-mechanism, gain-margin-diagnosis, oscillation-detection, transfer-function-reasoning |
| [laplace](laplace.md) | bayesian-updating, prior-elicitation, calibration-audit, probability-as-uncertainty, posterior-prediction |
| [vygotsky](vygotsky.md) | zone-of-proximal-development, scaffolding-and-fading, social-construction-of-knowledge, curriculum-sequencing, misconception-diagnosis |
| [schon](schon.md) | reflection-in-action, knowing-in-action, reframing, reflective-conversation-with-situation, strategy-switching |
| [rogerfisher](rogerfisher.md) | interests-vs-positions, batna-analysis, zone-of-possible-agreement, principled-negotiation, mutual-gain-design |
| [rogers](rogers.md) | adoption-curve-segmentation, chasm-diagnosis, diffusion-dynamics, adopter-category-analysis, innovation-attributes |
| [carnot](carnot.md) | efficiency-limit-derivation, reversibility-audit, entropy-production-localization, ideal-vs-actual-comparison, second-law-constraint |
| [ranganathan](ranganathan.md) | faceted-classification, five-laws-of-findability, navigation-design, colon-classification, information-scent-optimization |
| [erdos](erdos.md) | probabilistic-existence-proof, random-graph-threshold, extremal-combinatorics, collaborative-problem-decomposition, the-book-proof |
| [toulmin](toulmin.md) | claim-evidence-warrant, qualifier-and-rebuttal, backing-the-warrant, argument-mapping, field-dependent-standards |
| [cochrane](cochrane.md) | systematic-review-protocol, effect-size-extraction, heterogeneity-detection, publication-bias-audit, evidence-grading |
| [gadamer](gadamer.md) | hermeneutic-circle, horizon-fusion, pre-understanding-audit, explanation-vs-understanding, principle-of-charity |
| [geertz](geertz.md) | thick-description, emic-vs-etic, participant-observation, cultural-interpretation, reflexivity-in-fieldwork |
| [strauss](strauss.md) | open-coding, constant-comparison, theoretical-sampling, axial-coding, theoretical-saturation |
| [snow](snow.md) | outbreak-investigation, hills-criteria, epidemic-curve-analysis, attack-rate-calculation, case-definition |
| [feinstein](feinstein.md) | differential-diagnosis, likelihood-ratio-updating, treatment-threshold, evidence-based-practice, clinical-judgment-audit |
| [hart](hart.md) | open-texture-analysis, reasoning-by-precedent, rule-exception-structure, proportionality-balancing, ratio-decidendi |
| [mill](mill.md) | method-of-agreement, method-of-difference, qualitative-comparative-analysis, necessary-vs-sufficient, most-similar-most-different |
| [foucault](foucault.md) | genealogy-of-practice, discourse-formation-analysis, power-knowledge-nexus, archaeology-of-assumptions, subject-position-mapping |
| [schelling](schelling.md) | micro-to-macro-inference, tipping-point-detection, focal-point-coordination, unintended-aggregate-consequences, agent-based-reasoning |
| [bruner](bruner.md) | narrative-vs-paradigmatic, story-as-sensemaking, narrative-structure-analysis, canonical-breach-detection, identity-through-narrative |

---

## Evaluated and Rejected (no distinct primary-source-backed shape)

| Candidate | Closest existing coverage | Reason for rejection |
|---|---|---|
| Hawking | von Neumann (cross-domain transfer) | "Regime-boundary collision" is real but overlaps von Neumann; procedure reconstructed from math, not explicitly stated |
| Tesla | Einstein (gedankenexperiment) | Mental simulation overlaps Einstein; *My Inventions* is a retrospective autobiography, not a methodology document |
| Jobs | Engelbart + Hopper + Feynman | No primary-source methodology documents; keynotes are performances, not procedures |
| Gray | Shannon (source-channel-code) | Harmonic telegraph subsumed by Shannon; telautograph insight is interesting but thin and not explicitly articulated |
