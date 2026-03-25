/**
 * @module core/medical-graph-builder
 * @description Builds a neural knowledge graph for medical domain analysis.
 *
 * Encodes the pollen → antihistamine → desensitization domain as a
 * force-directed graph compatible with the Cortex visualization system.
 *
 * Node types map to the existing viz color scheme:
 * - domain          → System hubs (cyan)
 * - entry-point     → Allergens & triggers (green)
 * - recurring-pattern → Immune cells & mediators (blue)
 * - tool-preference → Drugs & interventions (amber)
 * - behavioral-feature → Biomarkers & monitoring (purple)
 * - blind-spot      → Failure modes & risks (gray)
 *
 * Edge types:
 * - has-entry       → "activates / triggers"
 * - has-pattern     → "produces / differentiates into"
 * - uses-tool       → "targets / treats"
 * - bridge          → "cross-system connection"
 * - has-feature     → "measured by"
 * - has-blindspot   → "risk factor"
 * - persistent-feature → "persistent across" (pink)
 *
 * @requires nothing (pure data construction)
 */

"use strict";

let _id = 0;
function id(prefix) { return `${prefix}_${_id++}`; }

/**
 * Build the pollen-allergy desensitization knowledge graph.
 * @returns {import('../shared/types').GraphData}
 */
function buildMedicalGraph() {
  _id = 0;
  const nodes = [];
  const edges = [];
  const blindSpotRegions = [];

  // ═══════════════════════════════════════════════════════════
  // DOMAIN HUBS — 7 system-level hubs
  // ═══════════════════════════════════════════════════════════

  const hubAllergens = addHub("Allergen Exposure", "allergen-exposure", 45);
  const hubInnate = addHub("Innate Immune Response", "innate-immune", 35);
  const hubAdaptive = addHub("Adaptive Immune Response", "adaptive-immune", 50);
  const hubEffector = addHub("Effector Cascade", "effector-cascade", 40);
  const hubPharmaco = addHub("Pharmacological Blockade", "pharmacology", 30);
  const hubAIT = addHub("Allergen Immunotherapy (AIT)", "immunotherapy", 55);
  const hubMonitor = addHub("Clinical Monitoring", "monitoring", 25);

  function addHub(label, domain, sessions) {
    const n = {
      id: id("domain"), type: "domain", label, domain,
      confidence: Math.min(sessions / 60, 1),
      sessionCount: sessions, color: "#00FFFF",
      size: Math.max(8, Math.min(30, sessions * 0.5)),
    };
    nodes.push(n);
    return n;
  }

  // ═══════════════════════════════════════════════════════════
  // ALLERGENS — entry-point nodes (green)
  // ═══════════════════════════════════════════════════════════

  const allergens = [
    { label: "Bet v 1 (Birch)", freq: 12, conf: 0.85, detail: "Major birch pollen allergen. PR-10 protein family. Cross-reacts with apple, hazelnut, cherry (oral allergy syndrome)." },
    { label: "Phl p 1 (Timothy)", freq: 10, conf: 0.80, detail: "Group 1 grass allergen. β-expansin. Affects 95% of grass-allergic patients." },
    { label: "Phl p 5 (Timothy)", freq: 8, conf: 0.75, detail: "Group 5 grass allergen. Ribonuclease. High IgE-binding. Key AIT target." },
    { label: "Der p 1 (Dust Mite)", freq: 9, conf: 0.78, detail: "Cysteine protease. Cleaves CD23 on B-cells, amplifying IgE production." },
    { label: "Amb a 1 (Ragweed)", freq: 7, conf: 0.70, detail: "Pectate lyase. Dominant ragweed allergen. 95% of ragweed-allergic bind this." },
    { label: "Ole e 1 (Olive)", freq: 5, conf: 0.55, detail: "Major olive pollen allergen. Mediterranean regions. Cross-reacts with ash, privet." },
  ];

  for (const a of allergens) {
    const n = { id: id("entry"), type: "entry-point", label: a.label, domain: "allergen-exposure",
      confidence: a.conf, frequency: a.freq, color: "#00FF88",
      size: Math.max(4, Math.min(15, a.freq * 2)),
      description: a.detail,
    };
    nodes.push(n);
    edges.push({ source: hubAllergens.id, target: n.id, type: "has-entry", weight: a.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // INNATE IMMUNE — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const innateComponents = [
    { label: "Epithelial Barrier", freq: 8, conf: 0.75, detail: "Nasal/bronchial epithelium. Releases TSLP, IL-25, IL-33 upon allergen contact. Gateway to sensitization." },
    { label: "TSLP (Thymic Stromal)", freq: 6, conf: 0.65, detail: "Master switch cytokine. Activates dendritic cells toward Th2 programming. Therapeutic target (tezepelumab)." },
    { label: "IL-33 (Alarmin)", freq: 7, conf: 0.70, detail: "Released from damaged epithelium. Activates ILC2s and mast cells. Amplifies Th2 cascade." },
    { label: "Dendritic Cells (DC)", freq: 10, conf: 0.82, detail: "Antigen-presenting cells. Capture allergen → migrate to lymph node → present to naive T-cells. Gate between innate and adaptive." },
    { label: "ILC2 (Innate Lymphoid)", freq: 5, conf: 0.55, detail: "Tissue-resident innate cells. Produce IL-5, IL-13 without antigen presentation. First responders to epithelial alarmins." },
  ];

  for (const c of innateComponents) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: c.label, domain: "innate-immune",
      confidence: c.conf, frequency: c.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, c.freq * 1.5)),
      description: c.detail,
    };
    nodes.push(n);
    edges.push({ source: hubInnate.id, target: n.id, type: "has-pattern", weight: c.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // ADAPTIVE IMMUNE — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const adaptiveComponents = [
    { label: "Naive T-cell → Th2", freq: 12, conf: 0.90, detail: "IL-4-dependent differentiation. Th2 cells produce IL-4, IL-5, IL-13. Central to allergic sensitization." },
    { label: "Th2 Cells", freq: 14, conf: 0.92, detail: "CD4+ T-helper type 2. Secrete IL-4 (IgE class switch), IL-5 (eosinophil recruitment), IL-13 (mucus, airway hyperreactivity)." },
    { label: "B-cell → IgE Class Switch", freq: 11, conf: 0.88, detail: "IL-4 + CD40L from Th2 → B-cell undergoes VDJ recombination to ε heavy chain. Produces allergen-specific IgE." },
    { label: "Allergen-Specific IgE", freq: 15, conf: 0.95, detail: "Binds FcεRI on mast cells/basophils. Half-life on mast cell surface: weeks-months. Primes for rapid degranulation on re-exposure." },
    { label: "Treg (Regulatory T)", freq: 10, conf: 0.85, detail: "CD4+CD25+FoxP3+. Produce IL-10, TGF-β. Suppress Th2. KEY TARGET of immunotherapy. Natural tolerance mechanism." },
    { label: "Th1 Counter-regulation", freq: 6, conf: 0.60, detail: "IFN-γ from Th1 inhibits Th2 differentiation. Th1/Th2 balance determines allergic vs. tolerant outcome." },
    { label: "IL-4 (Class Switch Signal)", freq: 9, conf: 0.80, detail: "Key Th2 cytokine. Drives IgE class switch in B-cells. Autocrine loop amplifies Th2 polarization. Target: dupilumab." },
    { label: "IL-5 (Eosinophil Signal)", freq: 8, conf: 0.75, detail: "Recruits and activates eosinophils. Late-phase inflammation. Target: mepolizumab, benralizumab." },
    { label: "IL-13 (Tissue Remodeling)", freq: 7, conf: 0.72, detail: "Mucus hypersecretion, goblet cell metaplasia, airway hyperreactivity. Drives chronic structural changes." },
  ];

  for (const c of adaptiveComponents) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: c.label, domain: "adaptive-immune",
      confidence: c.conf, frequency: c.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, c.freq * 1.5)),
      description: c.detail,
    };
    nodes.push(n);
    edges.push({ source: hubAdaptive.id, target: n.id, type: "has-pattern", weight: c.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // EFFECTOR CASCADE — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const effectorComponents = [
    { label: "Mast Cell (Tissue)", freq: 14, conf: 0.92, detail: "Tissue-resident sentinel. Surface FcεRI loaded with IgE. Cross-linking by allergen → immediate degranulation within seconds." },
    { label: "Basophil (Blood)", freq: 8, conf: 0.70, detail: "Circulating counterpart of mast cell. Measurable by flow cytometry (CD63/CD203c). Used for basophil activation test (BAT)." },
    { label: "Histamine (H1 → Symptoms)", freq: 15, conf: 0.95, detail: "Preformed in granules. H1 receptor: vasodilation, edema, itch, sneezing. H2 receptor: gastric acid + paradoxically promotes Treg induction." },
    { label: "Leukotrienes (CysLT1)", freq: 10, conf: 0.82, detail: "LTC4/D4/E4. De novo synthesized. Bronchoconstriction (1000x more potent than histamine), mucus secretion, vascular permeability." },
    { label: "Prostaglandin D2 (PGD2)", freq: 7, conf: 0.65, detail: "DP2/CRTH2 receptor. Nasal congestion. Recruits Th2 cells and eosinophils. Target: fevipiprant." },
    { label: "Eosinophils", freq: 9, conf: 0.78, detail: "Late-phase effectors. Arrive 6-12h post-exposure. Release Major Basic Protein (MBP) → epithelial damage → chronic remodeling." },
    { label: "Tryptase (Mast Cell)", freq: 5, conf: 0.50, detail: "Serine protease co-released with histamine. Serum marker for mast cell activation. Cleaves fibrinogen, activates PAR-2." },
  ];

  for (const c of effectorComponents) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: c.label, domain: "effector-cascade",
      confidence: c.conf, frequency: c.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, c.freq * 1.5)),
      description: c.detail,
    };
    nodes.push(n);
    edges.push({ source: hubEffector.id, target: n.id, type: "has-pattern", weight: c.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // PHARMACOLOGY — tool-preference nodes (amber)
  // ═══════════════════════════════════════════════════════════

  const drugs = [
    { label: "Cetirizine (H1 blocker)", ratio: 0.85, avg: 8, detail: "2nd-gen antihistamine. Blocks H1 receptor. Partial H2 crossover — may slightly impair Treg induction during AIT." },
    { label: "Fexofenadine (H1 blocker)", ratio: 0.80, avg: 7, detail: "2nd-gen antihistamine. Minimal H2 crossover. Preferred during AIT for breakthrough symptoms." },
    { label: "Montelukast (CysLT1 blocker)", ratio: 0.55, avg: 4, detail: "Leukotriene receptor antagonist. Addresses the 40% of symptoms antihistamines miss. Nasal congestion + bronchoconstriction." },
    { label: "Fluticasone (Nasal Steroid)", ratio: 0.75, avg: 6, detail: "Topical corticosteroid. Suppresses local inflammation (NF-κB pathway). Does NOT impair AIT — actually synergistic." },
    { label: "Omalizumab (Anti-IgE mAb)", ratio: 0.45, avg: 3, detail: "Binds free IgE → prevents FcεRI loading. Pre-treatment before rush AIT reduces anaphylaxis risk 5-fold. Expensive (~$1200/mo)." },
    { label: "Dupilumab (Anti-IL-4Rα)", ratio: 0.35, avg: 2, detail: "Blocks IL-4 and IL-13 signaling. Severe atopic disease. Not a replacement for AIT — works downstream, doesn't induce tolerance." },
    { label: "Mepolizumab (Anti-IL-5)", ratio: 0.30, avg: 2, detail: "Depletes eosinophils. Severe eosinophilic asthma add-on. Addresses late-phase but not root cause." },
  ];

  for (const d of drugs) {
    const n = { id: id("tool"), type: "tool-preference", label: d.label, domain: "pharmacology",
      ratio: d.ratio, avgPerSession: d.avg, color: "#FFB800",
      size: Math.max(4, Math.min(12, d.ratio * 15)),
      description: d.detail,
    };
    nodes.push(n);
    edges.push({ source: hubPharmaco.id, target: n.id, type: "uses-tool", weight: d.ratio });
  }

  // ═══════════════════════════════════════════════════════════
  // IMMUNOTHERAPY PROTOCOLS — tool-preference nodes (amber)
  // ═══════════════════════════════════════════════════════════

  const protocols = [
    { label: "SCIT (Subcutaneous)", ratio: 0.90, avg: 10, detail: "Gold standard. Build-up (weekly × 16wk) → maintenance (monthly × 3yr). Efficacy 85-90%. Risk: systemic reactions (1-2%)." },
    { label: "SLIT Tablets (Sublingual)", ratio: 0.85, avg: 9, detail: "Daily tablet under tongue. Grazax (grass), Itulazax (tree), Ragwitek (ragweed). Home-administered. Lower anaphylaxis risk." },
    { label: "Cluster Protocol (Accelerated)", ratio: 0.65, avg: 5, detail: "2-3 injections per visit. Reach maintenance in 4-6 weeks. Same efficacy, 3× less dropout than conventional." },
    { label: "Rush Protocol (1-3 days)", ratio: 0.50, avg: 4, detail: "Maintenance in 1-3 days. Hospital setting required. Pre-medicate with omalizumab. For severe cases / poor compliance." },
    { label: "CRD-Guided Selection", ratio: 0.70, avg: 6, detail: "Component-Resolved Diagnostics blood test. Identifies exact molecular allergens. Single high-dose > multi-allergen low-dose." },
    { label: "Pre-seasonal Start (Oct)", ratio: 0.60, avg: 5, detail: "Begin SCIT 4 months before pollen season. Immune system not in Th2 overdrive. Critical timing for success." },
    { label: "IgG4 Blocking Antibodies", ratio: 0.80, avg: 8, detail: "AIT induces IgG4 that competes with IgE for allergen binding. Catches allergen before it reaches mast cell surface." },
    { label: "Treg Induction (IL-10)", ratio: 0.85, avg: 9, detail: "Sustained allergen exposure → CD4+CD25+FoxP3+ Treg. Produce IL-10, TGF-β. Actively suppress Th2. The actual cure." },
  ];

  for (const p of protocols) {
    const n = { id: id("tool"), type: "tool-preference", label: p.label, domain: "immunotherapy",
      ratio: p.ratio, avgPerSession: p.avg, color: "#FFB800",
      size: Math.max(4, Math.min(12, p.ratio * 15)),
      description: p.detail,
    };
    nodes.push(n);
    edges.push({ source: hubAIT.id, target: n.id, type: "uses-tool", weight: p.ratio });
  }

  // ═══════════════════════════════════════════════════════════
  // BIOMARKERS — behavioral-feature nodes (purple)
  // ═══════════════════════════════════════════════════════════

  const biomarkers = [
    { label: "Specific IgE (sIgE)", activation: 0.90, detail: "Serum allergen-specific IgE. Baseline: varies. Rises initially during AIT then drops. >0.35 kU/L = sensitized." },
    { label: "Specific IgG4 (sIgG4)", activation: 0.95, detail: "KEY SUCCESS MARKER. Baseline <1 kU/L → target >20 kU/L by month 12. Blocking antibody that competes with IgE." },
    { label: "IgE/IgG4 Ratio", activation: 0.92, detail: "Most predictive single biomarker. Baseline >10 → target <2. Ratio <2 = tolerance established. Check at 6, 12, 24 months." },
    { label: "Basophil Activation (BAT)", activation: 0.80, detail: "Flow cytometry: CD63+ basophils after allergen stimulation. Baseline >40% → target <15%. Functional readout of desensitization." },
    { label: "Nasal Provocation (NPT)", activation: 0.70, detail: "Direct allergen challenge to nasal mucosa. Threshold in SBE (Standardized Biological Equivalent). Target: >1000 SBE." },
    { label: "Serum Tryptase", activation: 0.50, detail: "Mast cell activation marker. Baseline elevated = higher AIT reaction risk. Monitor pre/post each injection." },
    { label: "Eosinophil Count (Blood)", activation: 0.65, detail: "Peripheral blood eosinophils. >300/μL = active allergic inflammation. Should decrease with successful AIT." },
    { label: "FeNO (Exhaled Nitric Oxide)", activation: 0.60, detail: "Non-invasive airway inflammation marker. >25 ppb = eosinophilic airway inflammation. Tracks response in allergic asthma." },
    { label: "FoxP3+ Treg Frequency", activation: 0.75, detail: "Research biomarker. Flow cytometry on PBMCs. CD4+CD25+FoxP3+. Rising Treg frequency = tolerance induction confirmed." },
  ];

  for (const b of biomarkers) {
    const n = { id: id("feature"), type: "behavioral-feature", label: b.label, domain: "monitoring",
      activation: b.activation, color: "#a855f7",
      size: Math.max(3, Math.min(10, b.activation * 12)),
      description: b.detail,
    };
    nodes.push(n);
    edges.push({ source: hubMonitor.id, target: n.id, type: "has-feature", weight: b.activation });
  }

  // ═══════════════════════════════════════════════════════════
  // FAILURE MODES — blind-spot nodes (gray)
  // ═══════════════════════════════════════════════════════════

  const failures = [
    { value: "Insufficient Dose", severity: "high", desc: "Standard 16-week build-up → 30% dropout before maintenance. Subtherapeutic exposure fails to flip Th2→Treg.", sug: "Use cluster/rush protocol. Reach maintenance in 4-6 weeks." },
    { value: "Wrong Allergen Selection", severity: "high", desc: "Polysensitized patients get diluted multi-allergen extracts. Each below Treg-induction threshold.", sug: "CRD blood panel first. Identify molecular allergens. Single high-dose." },
    { value: "Antihistamine Interference", severity: "medium", desc: "Prophylactic H1 blockade during AIT may suppress H2-mediated Treg induction. Paradoxical tolerance reduction.", sug: "Use fexofenadine (minimal H2). Avoid antihistamines 12h pre-injection." },
    { value: "Timing Mismatch", severity: "medium", desc: "Starting AIT mid-season while pollen counts peak. Immune system already in full Th2 mode.", sug: "Start SCIT 4 months pre-season (October for spring pollens)." },
    { value: "No Biomarker Monitoring", severity: "high", desc: "3 years of injections with no IgG4 tracking. Patients quit at month 8, right before inflection point.", sug: "Track IgG4, IgE/IgG4 ratio, BAT at 6/12/24 months." },
    { value: "Premature Discontinuation", severity: "high", desc: "Stopping AIT before 3 years. Tolerance not fully established. Relapse within 1-2 years.", sug: "Minimum 3 years. Continue SLIT maintenance through year 4." },
    { value: "Anaphylaxis Risk (SCIT)", severity: "medium", desc: "Systemic reactions in 1-2% of SCIT patients. Higher with rush protocols or uncontrolled asthma.", sug: "Pre-medicate with omalizumab for rush. 30-min observation post-injection." },
  ];

  for (const f of failures) {
    const n = { id: id("bs"), type: "blind-spot", label: f.value, domain: "immunotherapy",
      confidence: 0.1, severity: f.severity, description: f.desc, suggestion: f.sug,
      color: "#333344", size: 3, _bs: true,
    };
    nodes.push(n);
    edges.push({ source: hubAIT.id, target: n.id, type: "has-blindspot", weight: 0.08 });
    blindSpotRegions.push({ domain: "immunotherapy", type: "failure-mode", value: f.value, severity: f.severity, description: f.desc, suggestion: f.sug });
  }

  // ═══════════════════════════════════════════════════════════
  // CROSS-SYSTEM BRIDGES — causal connections between hubs
  // ═══════════════════════════════════════════════════════════

  // Allergens → Innate
  edges.push({ source: hubAllergens.id, target: hubInnate.id, type: "bridge", weight: 0.9, label: "allergen dissolves on mucosa" });
  // Innate → Adaptive
  edges.push({ source: hubInnate.id, target: hubAdaptive.id, type: "bridge", weight: 0.85, label: "DC presents to T-cell" });
  // Adaptive → Effector
  edges.push({ source: hubAdaptive.id, target: hubEffector.id, type: "bridge", weight: 0.9, label: "IgE arms mast cells" });
  // Effector → Pharmacology (blockade)
  edges.push({ source: hubEffector.id, target: hubPharmaco.id, type: "bridge", weight: 0.7, label: "symptoms → drug blockade" });
  // Pharmacology → Effector (inhibits — same edge, shows the feedback)
  edges.push({ source: hubPharmaco.id, target: hubEffector.id, type: "bridge", weight: 0.5, label: "blocks 40% of mediators" });
  // AIT → Adaptive (rewires)
  edges.push({ source: hubAIT.id, target: hubAdaptive.id, type: "bridge", weight: 0.95, label: "Th2 → Treg reprogramming" });
  // AIT → Effector (suppresses via IgG4)
  edges.push({ source: hubAIT.id, target: hubEffector.id, type: "bridge", weight: 0.8, label: "IgG4 blocks IgE cross-linking" });
  // Monitor → AIT (feedback loop)
  edges.push({ source: hubMonitor.id, target: hubAIT.id, type: "bridge", weight: 0.75, label: "biomarker-guided dose adjustment" });
  // Allergens → AIT (the input)
  edges.push({ source: hubAllergens.id, target: hubAIT.id, type: "bridge", weight: 0.85, label: "controlled re-exposure" });
  // Innate → Effector (ILC2 → eosinophils)
  edges.push({ source: hubInnate.id, target: hubEffector.id, type: "bridge", weight: 0.6, label: "ILC2 → eosinophil recruitment" });
  // AIT → Innate (reduces epithelial alarmin release)
  edges.push({ source: hubAIT.id, target: hubInnate.id, type: "bridge", weight: 0.5, label: "reduces TSLP/IL-33 release" });

  // ═══════════════════════════════════════════════════════════
  // INTRA-SYSTEM CAUSAL EDGES (fine-grained wiring)
  // ═══════════════════════════════════════════════════════════

  // Helper to find nodes
  const find = (label) => nodes.find((n) => n.label === label);

  // Epithelial → TSLP, IL-33
  link(find("Epithelial Barrier"), find("TSLP (Thymic Stromal)"), "has-pattern", 0.8);
  link(find("Epithelial Barrier"), find("IL-33 (Alarmin)"), "has-pattern", 0.8);
  // TSLP → DC
  link(find("TSLP (Thymic Stromal)"), find("Dendritic Cells (DC)"), "has-pattern", 0.85);
  // IL-33 → ILC2
  link(find("IL-33 (Alarmin)"), find("ILC2 (Innate Lymphoid)"), "has-pattern", 0.75);
  // DC → Naive→Th2
  link(find("Dendritic Cells (DC)"), find("Naive T-cell → Th2"), "has-pattern", 0.9);
  // Th2 → IL-4, IL-5, IL-13
  link(find("Th2 Cells"), find("IL-4 (Class Switch Signal)"), "has-pattern", 0.9);
  link(find("Th2 Cells"), find("IL-5 (Eosinophil Signal)"), "has-pattern", 0.85);
  link(find("Th2 Cells"), find("IL-13 (Tissue Remodeling)"), "has-pattern", 0.8);
  // IL-4 → IgE class switch
  link(find("IL-4 (Class Switch Signal)"), find("B-cell → IgE Class Switch"), "has-pattern", 0.92);
  // B-cell → IgE
  link(find("B-cell → IgE Class Switch"), find("Allergen-Specific IgE"), "has-pattern", 0.95);
  // IgE → Mast Cell
  link(find("Allergen-Specific IgE"), find("Mast Cell (Tissue)"), "has-pattern", 0.95);
  // IgE → Basophil
  link(find("Allergen-Specific IgE"), find("Basophil (Blood)"), "has-pattern", 0.8);
  // Mast Cell → Histamine, Leukotrienes, PGD2, Tryptase
  link(find("Mast Cell (Tissue)"), find("Histamine (H1 → Symptoms)"), "has-pattern", 0.95);
  link(find("Mast Cell (Tissue)"), find("Leukotrienes (CysLT1)"), "has-pattern", 0.85);
  link(find("Mast Cell (Tissue)"), find("Prostaglandin D2 (PGD2)"), "has-pattern", 0.7);
  link(find("Mast Cell (Tissue)"), find("Tryptase (Mast Cell)"), "has-pattern", 0.6);
  // IL-5 → Eosinophils
  link(find("IL-5 (Eosinophil Signal)"), find("Eosinophils"), "has-pattern", 0.88);
  // Treg → suppresses Th2 (counter-edge)
  link(find("Treg (Regulatory T)"), find("Th2 Cells"), "has-pattern", 0.85);
  // Th1 → suppresses Th2
  link(find("Th1 Counter-regulation"), find("Th2 Cells"), "has-pattern", 0.6);

  // Drug → target edges
  link(find("Cetirizine (H1 blocker)"), find("Histamine (H1 → Symptoms)"), "uses-tool", 0.85);
  link(find("Fexofenadine (H1 blocker)"), find("Histamine (H1 → Symptoms)"), "uses-tool", 0.80);
  link(find("Montelukast (CysLT1 blocker)"), find("Leukotrienes (CysLT1)"), "uses-tool", 0.75);
  link(find("Omalizumab (Anti-IgE mAb)"), find("Allergen-Specific IgE"), "uses-tool", 0.90);
  link(find("Dupilumab (Anti-IL-4Rα)"), find("IL-4 (Class Switch Signal)"), "uses-tool", 0.85);
  link(find("Mepolizumab (Anti-IL-5)"), find("Eosinophils"), "uses-tool", 0.80);

  // AIT → Treg
  link(find("Treg Induction (IL-10)"), find("Treg (Regulatory T)"), "uses-tool", 0.95);
  // AIT IgG4 → blocks IgE loading
  link(find("IgG4 Blocking Antibodies"), find("Allergen-Specific IgE"), "uses-tool", 0.90);

  // Biomarker → what they measure
  link(find("Specific IgE (sIgE)"), find("Allergen-Specific IgE"), "has-feature", 0.9);
  link(find("Specific IgG4 (sIgG4)"), find("IgG4 Blocking Antibodies"), "has-feature", 0.95);
  link(find("Basophil Activation (BAT)"), find("Basophil (Blood)"), "has-feature", 0.85);
  link(find("Serum Tryptase"), find("Mast Cell (Tissue)"), "has-feature", 0.7);
  link(find("Eosinophil Count (Blood)"), find("Eosinophils"), "has-feature", 0.75);
  link(find("FoxP3+ Treg Frequency"), find("Treg (Regulatory T)"), "has-feature", 0.8);

  // Persistent features across systems (pink edges)
  edges.push({ source: hubAdaptive.id, target: hubAIT.id, type: "persistent-feature", weight: 0.95, label: "IgE/IgG4 axis", color: "#ec4899" });
  edges.push({ source: hubEffector.id, target: hubMonitor.id, type: "persistent-feature", weight: 0.8, label: "mast cell activation readout", color: "#ec4899" });
  edges.push({ source: hubInnate.id, target: hubMonitor.id, type: "persistent-feature", weight: 0.65, label: "FeNO/eosinophil tracking", color: "#ec4899" });

  function link(source, target, type, weight) {
    if (!source || !target) return;
    edges.push({ source: source.id, target: target.id, type, weight });
  }

  return { nodes, edges, blindSpotRegions };
}

module.exports = { buildMedicalGraph };
