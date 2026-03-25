/**
 * Builds a neural knowledge graph for the payment form validation pipeline.
 * Output artifact — NOT part of Cortex core engine.
 *
 * Node mapping to Cortex viz color scheme:
 * - domain (cyan)           → System layers
 * - entry-point (green)     → Input fields & raw data
 * - recurring-pattern (blue) → Validation rules & algorithms
 * - tool-preference (amber)  → Outputs & transformations
 * - behavioral-feature (purple) → Security & compliance checks
 * - blind-spot (gray)        → Attack vectors & failure modes
 */

"use strict";

let _id = 0;
function id(prefix) { return `${prefix}_${_id++}`; }

function buildPaymentGraph() {
  _id = 0;
  const nodes = [];
  const edges = [];
  const blindSpotRegions = [];

  // ═══════════════════════════════════════════════════════════
  // SYSTEM HUBS — 6 layers of the payment pipeline
  // ═══════════════════════════════════════════════════════════

  const hubInput = addHub("Raw Input", "raw-input", 40);
  const hubSanitize = addHub("Sanitization", "sanitization", 30);
  const hubValidation = addHub("Field Validation", "field-validation", 55);
  const hubCross = addHub("Cross-Validation", "cross-validation", 25);
  const hubSecurity = addHub("Security Layer", "security", 35);
  const hubOutput = addHub("Result Assembly", "result-assembly", 30);

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
  // INPUT FIELDS — entry-point nodes (green)
  // ═══════════════════════════════════════════════════════════

  const inputs = [
    { label: "Card Number (PAN)", freq: 15, conf: 0.95, description: "Primary Account Number. 13-19 digits. May contain spaces, dashes. Embossed or flat-printed. Carries issuer ID (IIN/BIN) in first 6 digits." },
    { label: "Expiry Date (MM/YY)", freq: 12, conf: 0.90, description: "Card expiration. Magnetic stripe encodes YYMM. EMV chip may differ. Card valid through last day of stated month." },
    { label: "CVV/CVC Code", freq: 12, conf: 0.88, description: "Card Verification Value. 3 digits (Visa/MC/Discover) or 4 digits (Amex). NOT stored on magnetic stripe — proves physical card possession." },
    { label: "Cardholder Name", freq: 10, conf: 0.80, description: "Name as embossed on card. May differ from billing name. Used for AVS partial match in some processors." },
  ];

  for (const inp of inputs) {
    const n = { id: id("entry"), type: "entry-point", label: inp.label, domain: "raw-input",
      confidence: inp.conf, frequency: inp.freq, color: "#00FF88",
      size: Math.max(4, Math.min(15, inp.freq * 2)), description: inp.description,
    };
    nodes.push(n);
    edges.push({ source: hubInput.id, target: n.id, type: "has-entry", weight: inp.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // SANITIZATION — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const sanitizers = [
    { label: "Strip Non-Digits", freq: 10, conf: 0.95, description: "Remove spaces, dashes, dots, letters from PAN. Regex: /\\D/g → ''. Preserves only [0-9]. Prevents injection via format characters." },
    { label: "Trim Whitespace", freq: 8, conf: 0.85, description: "Leading/trailing whitespace removal on all string fields. Prevents \" John Doe \" ≠ \"John Doe\" mismatches." },
    { label: "Normalize Expiry", freq: 7, conf: 0.80, description: "Parse MM/YY or MM/YYYY into (month, year) integers. 2-digit year → +2000. Handles flexible spacing around slash." },
  ];

  for (const s of sanitizers) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: s.label, domain: "sanitization",
      confidence: s.conf, frequency: s.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, s.freq * 1.5)), description: s.description,
    };
    nodes.push(n);
    edges.push({ source: hubSanitize.id, target: n.id, type: "has-pattern", weight: s.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // VALIDATION RULES — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const validators = [
    { label: "Luhn Mod-10 Checksum", freq: 15, conf: 0.98, description: "ISO/IEC 7812-1. From rightmost digit, double every 2nd, subtract 9 if >9, sum all. Valid if sum % 10 === 0. Catches single-digit errors and adjacent transpositions." },
    { label: "IIN/BIN Prefix Detection", freq: 12, conf: 0.92, description: "First 6 digits identify issuer. Visa: 4xxx. MC: 51-55/2221-2720. Amex: 34/37. Discover: 6011/644-649/65. Diners: 300-305/36/38. JCB: 35/2131/1800." },
    { label: "Length per Card Type", freq: 10, conf: 0.90, description: "Visa: 13/16/19. MC: 16. Amex: 15. Discover: 16/19. Diners: 14. JCB: 15/16. Wrong length for detected type = reject." },
    { label: "Month Range (01-12)", freq: 8, conf: 0.95, description: "Calendar month validation. Reject 00 and 13+. Combined with year to check expiry against current date." },
    { label: "Expiry Not Past", freq: 10, conf: 0.92, description: "Card expires end of stated month. Compare against current date. Reject if expiry < now. Allow current month (still valid through month-end)." },
    { label: "Expiry Max Future (20yr)", freq: 5, conf: 0.70, description: "Reject expiry dates >20 years in future. Catches typos (2099) and test probes. Real cards rarely exceed 5-year validity." },
    { label: "CVV Digits Only", freq: 8, conf: 0.90, description: "Reject non-numeric CVV. No letters, spaces, or special characters. Strict regex: /^\\d+$/." },
    { label: "CVV Length Check", freq: 10, conf: 0.92, description: "3 digits for Visa/MC/Discover/Diners/JCB. 4 digits for Amex (CID). Length mismatch = reject." },
    { label: "Name Non-Empty", freq: 6, conf: 0.85, description: "Cardholder name required, minimum 2 characters. Prevents empty submissions and single-initial entries." },
    { label: "Name No Digits", freq: 5, conf: 0.80, description: "Names don't contain numbers. Catches copy-paste errors where card number lands in name field." },
    { label: "Name Max Length (50)", freq: 4, conf: 0.75, description: "Prevent buffer overflow or abuse. 50 chars accommodates longest real names. Embossed cards limited to 26 chars." },
  ];

  for (const v of validators) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: v.label, domain: "field-validation",
      confidence: v.conf, frequency: v.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, v.freq * 1.5)), description: v.description,
    };
    nodes.push(n);
    edges.push({ source: hubValidation.id, target: n.id, type: "has-pattern", weight: v.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // CROSS-VALIDATION — recurring-pattern nodes (blue)
  // ═══════════════════════════════════════════════════════════

  const crossRules = [
    { label: "CVV Length ↔ Card Type", freq: 10, conf: 0.95, description: "Amex detected → require 4-digit CVV. All others → require 3-digit. Type detection feeds CVV validator dynamically." },
    { label: "Error Accumulation", freq: 8, conf: 0.88, description: "NOT fail-fast. All 4 fields validated independently. All errors collected and returned at once. User fixes everything in one pass." },
  ];

  for (const cr of crossRules) {
    const n = { id: id("pattern"), type: "recurring-pattern", label: cr.label, domain: "cross-validation",
      confidence: cr.conf, frequency: cr.freq, color: "#0080FF",
      size: Math.max(4, Math.min(15, cr.freq * 1.5)), description: cr.description,
    };
    nodes.push(n);
    edges.push({ source: hubCross.id, target: n.id, type: "has-pattern", weight: cr.conf });
  }

  // ═══════════════════════════════════════════════════════════
  // SECURITY — behavioral-feature nodes (purple)
  // ═══════════════════════════════════════════════════════════

  const security = [
    { label: "PAN Never Stored", activation: 0.95, description: "Raw card number exists only during validation. Result contains only masked number (•••• 4242) and last4. PCI DSS requirement 3.4." },
    { label: "Masked Output Only", activation: 0.90, description: "maskCardNumber() replaces all but last 4 digits with bullets. Grouped in 4s. Prevents accidental PAN logging or display." },
    { label: "No Network Calls", activation: 0.85, description: "Entire validation is pure/local. No external API. Card data never leaves the process. Reduces PCI scope to SAQ A-EP." },
    { label: "Input Sanitization", activation: 0.80, description: "All inputs stripped/trimmed before processing. Prevents format string injection, SQL fragments in name field, oversized payloads." },
    { label: "CVV Proves Possession", activation: 0.75, description: "CVV is not on magnetic stripe or stored by merchants. Its presence proves cardholder has physical card (or card-on-file)." },
    { label: "Luhn Catches Entry Errors", activation: 0.88, description: "Luhn mod-10 detects 100% of single-digit errors and 97.8% of adjacent transpositions. First line of defense before network call." },
    { label: "PCI DSS Alignment", activation: 0.70, description: "Pure client-side validation + masking aligns with PCI DSS v4.0 Requirement 3 (protect stored data) and Requirement 4 (encrypt transmission)." },
  ];

  for (const sec of security) {
    const n = { id: id("feature"), type: "behavioral-feature", label: sec.label, domain: "security",
      activation: sec.activation, color: "#a855f7",
      size: Math.max(3, Math.min(10, sec.activation * 12)), description: sec.description,
    };
    nodes.push(n);
    edges.push({ source: hubSecurity.id, target: n.id, type: "has-feature", weight: sec.activation });
  }

  // ═══════════════════════════════════════════════════════════
  // OUTPUTS — tool-preference nodes (amber)
  // ═══════════════════════════════════════════════════════════

  const outputs = [
    { label: "PaymentFormResult", ratio: 0.95, avg: 10, description: "Top-level result: { valid, fields, errors, card }. Single object captures entire form state." },
    { label: "Per-Field Results", ratio: 0.90, avg: 8, description: "Each field gets { valid, errors, ...metadata }. Card field includes detected type. Expiry includes parsed month/year." },
    { label: "Flattened Error Array", ratio: 0.85, avg: 7, description: "All errors prefixed by field name: 'Card: fails Luhn', 'Expiry: expired'. Ready for UI toast or summary display." },
    { label: "Card Summary (if valid)", ratio: 0.80, avg: 6, description: "Only populated on success: { maskedNumber, last4, type, label, expiryMonth, expiryYear, cardholderName }. Safe to log/display." },
    { label: "Masked Card Number", ratio: 0.75, avg: 5, description: "•••• •••• •••• 4242 format. All but last 4 replaced. Grouped in 4s. Safe for receipts, confirmations, logs." },
  ];

  for (const o of outputs) {
    const n = { id: id("tool"), type: "tool-preference", label: o.label, domain: "result-assembly",
      ratio: o.ratio, avgPerSession: o.avg, color: "#FFB800",
      size: Math.max(4, Math.min(12, o.ratio * 15)), description: o.description,
    };
    nodes.push(n);
    edges.push({ source: hubOutput.id, target: n.id, type: "uses-tool", weight: o.ratio });
  }

  // ═══════════════════════════════════════════════════════════
  // FAILURE MODES — blind-spot nodes (gray)
  // ═══════════════════════════════════════════════════════════

  const failures = [
    { value: "BIN Table Staleness", severity: "medium", description: "Card type detection uses static IIN/BIN prefixes. New issuer ranges (e.g., UnionPay, Verve) not covered. Table needs periodic update.", suggestion: "Add UnionPay (62xxxx) and Verve (506xxx) ranges. Review BIN table quarterly." },
    { value: "No Rate Limiting", severity: "high", description: "Pure validation has no throttling. Attacker can brute-force valid PANs by iterating Luhn-valid numbers at CPU speed.", suggestion: "Add rate limiting at the caller level. Max 5 validation attempts per minute per session." },
    { value: "No BIN Blacklisting", severity: "medium", description: "Known fraudulent BIN ranges not filtered. Stolen card batches often share BIN prefix.", suggestion: "Integrate BIN reputation check before forwarding to payment processor." },
    { value: "Regex ReDoS Risk", severity: "low", description: "Expiry regex is simple (no catastrophic backtracking). But name field has no regex — only length/digit checks. Safe currently.", suggestion: "If name regex is added later, audit for ReDoS with safe-regex or similar." },
    { value: "No Locale-Aware Names", severity: "low", description: "Name validation rejects digits but allows all Unicode. CJK names, diacritics, single-word names (mononyms) all pass. May be too permissive for some regions.", suggestion: "Consider locale-specific name validation if processing region is restricted." },
    { value: "Test Card Leakage", severity: "medium", description: "Known test PANs (4242...4242, 4000...0002) pass all validation. In production, these should be rejected or flagged.", suggestion: "Add test card detection: reject known Stripe/Braintree test PANs in production mode." },
  ];

  for (const f of failures) {
    const n = { id: id("bs"), type: "blind-spot", label: f.value, domain: "security",
      confidence: 0.1, severity: f.severity, description: f.description, suggestion: f.suggestion,
      color: "#333344", size: 3, _bs: true,
    };
    nodes.push(n);
    edges.push({ source: hubSecurity.id, target: n.id, type: "has-blindspot", weight: 0.08 });
    blindSpotRegions.push({ domain: "security", type: "attack-vector", value: f.value, severity: f.severity, description: f.description, suggestion: f.suggestion });
  }

  // ═══════════════════════════════════════════════════════════
  // PIPELINE BRIDGES — causal flow between hubs
  // ═══════════════════════════════════════════════════════════

  edges.push({ source: hubInput.id, target: hubSanitize.id, type: "bridge", weight: 0.95, label: "raw → clean" });
  edges.push({ source: hubSanitize.id, target: hubValidation.id, type: "bridge", weight: 0.95, label: "sanitized → validate" });
  edges.push({ source: hubValidation.id, target: hubCross.id, type: "bridge", weight: 0.90, label: "field results → cross-check" });
  edges.push({ source: hubCross.id, target: hubOutput.id, type: "bridge", weight: 0.85, label: "all checks → assemble" });
  edges.push({ source: hubSecurity.id, target: hubSanitize.id, type: "bridge", weight: 0.80, label: "sanitization is security" });
  edges.push({ source: hubSecurity.id, target: hubOutput.id, type: "bridge", weight: 0.85, label: "masking enforced at output" });
  edges.push({ source: hubValidation.id, target: hubSecurity.id, type: "bridge", weight: 0.70, label: "Luhn = fraud first-pass" });

  // ═══════════════════════════════════════════════════════════
  // INTRA-SYSTEM CAUSAL EDGES
  // ═══════════════════════════════════════════════════════════

  const find = (label) => nodes.find((n) => n.label === label);

  // Input → Sanitizer edges
  link(find("Card Number (PAN)"), find("Strip Non-Digits"), "has-pattern", 0.95);
  link(find("Expiry Date (MM/YY)"), find("Normalize Expiry"), "has-pattern", 0.90);
  link(find("Cardholder Name"), find("Trim Whitespace"), "has-pattern", 0.85);
  link(find("CVV/CVC Code"), find("Trim Whitespace"), "has-pattern", 0.80);

  // Sanitizer → Validator edges
  link(find("Strip Non-Digits"), find("Luhn Mod-10 Checksum"), "has-pattern", 0.95);
  link(find("Strip Non-Digits"), find("IIN/BIN Prefix Detection"), "has-pattern", 0.92);
  link(find("Strip Non-Digits"), find("Length per Card Type"), "has-pattern", 0.90);
  link(find("Normalize Expiry"), find("Month Range (01-12)"), "has-pattern", 0.90);
  link(find("Normalize Expiry"), find("Expiry Not Past"), "has-pattern", 0.92);
  link(find("Normalize Expiry"), find("Expiry Max Future (20yr)"), "has-pattern", 0.70);
  link(find("Trim Whitespace"), find("CVV Digits Only"), "has-pattern", 0.88);
  link(find("Trim Whitespace"), find("Name Non-Empty"), "has-pattern", 0.85);

  // Validator → Cross-validator
  link(find("IIN/BIN Prefix Detection"), find("CVV Length ↔ Card Type"), "has-pattern", 0.95);
  link(find("CVV Length Check"), find("CVV Length ↔ Card Type"), "has-pattern", 0.90);

  // Cross-validator → Output
  link(find("Error Accumulation"), find("Flattened Error Array"), "uses-tool", 0.90);
  link(find("Error Accumulation"), find("Per-Field Results"), "uses-tool", 0.88);

  // Security → output enforcement
  link(find("PAN Never Stored"), find("Masked Output Only"), "has-feature", 0.95);
  link(find("Masked Output Only"), find("Masked Card Number"), "uses-tool", 0.92);
  link(find("Masked Output Only"), find("Card Summary (if valid)"), "uses-tool", 0.88);
  link(find("Luhn Catches Entry Errors"), find("Luhn Mod-10 Checksum"), "has-feature", 0.95);
  link(find("CVV Proves Possession"), find("CVV Length Check"), "has-feature", 0.85);
  link(find("Input Sanitization"), find("Strip Non-Digits"), "has-feature", 0.90);

  // Persistent feature edges (pink) — patterns that span the full pipeline
  edges.push({ source: hubInput.id, target: hubOutput.id, type: "persistent-feature", weight: 0.95, label: "PAN never persists raw", color: "#ec4899" });
  edges.push({ source: hubValidation.id, target: hubOutput.id, type: "persistent-feature", weight: 0.90, label: "error accumulation throughout", color: "#ec4899" });
  edges.push({ source: hubSecurity.id, target: hubValidation.id, type: "persistent-feature", weight: 0.85, label: "every rule is a security boundary", color: "#ec4899" });

  function link(source, target, type, weight) {
    if (!source || !target) return;
    edges.push({ source: source.id, target: target.id, type, weight });
  }

  return { nodes, edges, blindSpotRegions };
}

// ── CLI launcher ──────────────────────────────────────────────────────────

if (require.main === module) {
  const { startUIServer, shutdownServer } = require("../mcp-server/server/http-server");
  const { execSync } = require("child_process");
  const path = require("path");

  const htmlFile = path.join(__dirname, "..", "ui", "payment-viz.html");

  (async () => {
    const graph = buildPaymentGraph();

    console.log("╔══════════════════════════════════════════════════════════╗");
    console.log("║  J.A.R.V.I.S. — Payment Form Knowledge Graph           ║");
    console.log("║  Card Validation Pipeline Neural Map                     ║");
    console.log("╚══════════════════════════════════════════════════════════╝");
    console.log("");
    console.log(`  Nodes:       ${graph.nodes.length}`);
    console.log(`  Edges:       ${graph.edges.length}`);
    console.log(`  Blind Spots: ${graph.blindSpotRegions.length}`);

    const types = {};
    for (const n of graph.nodes) types[n.type] = (types[n.type] || 0) + 1;
    console.log("");
    console.log("  Node breakdown:");
    console.log(`    Pipeline layers (cyan):   ${types["domain"] || 0}`);
    console.log(`    Input fields (green):     ${types["entry-point"] || 0}`);
    console.log(`    Validation rules (blue):  ${types["recurring-pattern"] || 0}`);
    console.log(`    Outputs (amber):          ${types["tool-preference"] || 0}`);
    console.log(`    Security checks (purple): ${types["behavioral-feature"] || 0}`);
    console.log(`    Attack vectors (gray):    ${types["blind-spot"] || 0}`);
    console.log("");

    const url = await startUIServer(graph, { htmlFile });
    console.log(`  → Visualization: ${url}`);
    console.log("  → Auto-shutdown after 10 min idle");

    try { execSync(`open "${url}"`, { stdio: "ignore" }); } catch (_) {
      try { execSync(`xdg-open "${url}"`, { stdio: "ignore" }); } catch (_) {}
    }

    process.on("SIGINT", () => { shutdownServer(); process.exit(0); });
  })();
}

module.exports = { buildPaymentGraph };
