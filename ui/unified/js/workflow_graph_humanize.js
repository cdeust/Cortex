// Cortex Workflow Graph — plain-language humanization helpers.
//
// The raw node data the backend emits uses technical vocabulary
// (kind="symbol", stage="EARLY_LTP", heat=0.534, symbol_type="function").
// Non-technical users look at that and see an opaque data dump. This
// module translates every raw field into everyday English via the
// label tables in workflow_graph_labels.js.
//
// Exports JUG._wfgHumanize = {
//   kindLabel, kindIntro, plainDescription, stageLabel, stageHint,
//   symbolTypeLabel, edgeVerb, prettyFieldKey, primaryClusterLabel,
//   heatBadge,
// };
//
// Pure presentation logic — no DOM, no side effects. The panel imports
// these helpers and composes the DOM. The labels live in their own
// module (Dijkstra compliance — humanize module was breaching the
// project 300-line rule; label tables factor out cleanly as pure data).

(function () {
  function L() {
    return (window.JUG && window.JUG._wfgLabels) || {};
  }

  function kindLabel(kind) {
    return (L().KIND_LABELS || {})[kind] || kind || 'Item';
  }

  function kindIntro(kind) {
    return (L().KIND_INTROS || {})[kind] || 'an item Cortex tracked';
  }

  function stageLabel(stage) {
    if (!stage) return null;
    var key = String(stage).toLowerCase();
    return (L().STAGE_LABELS || {})[key] || stage;
  }

  function stageHint(stage) {
    if (!stage) return null;
    var key = String(stage).toLowerCase();
    return (L().STAGE_HINTS || {})[key] || null;
  }

  function symbolTypeLabel(type) {
    if (!type) return null;
    return (L().SYMBOL_TYPE_LABELS || {})[String(type).toLowerCase()] || type;
  }

  function edgeVerb(kind) {
    return (L().EDGE_VERBS || {})[kind] || kind || 'relates to';
  }

  // Human-readable key for a raw field name. ``first_seen`` → "First seen".
  // Falls back to the raw key when we don't have a translation.
  function prettyFieldKey(raw) {
    if (!raw) return '';
    var map = L().FIELD_LABELS || {};
    if (map[raw]) return map[raw];
    return String(raw).replace(/_/g, ' ').replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function primaryClusterLabel(raw) {
    if (!raw) return null;
    var map = L().PRIMARY_CLUSTER_LABELS || {};
    return map[String(raw).toLowerCase()] || raw;
  }

  // Heat is a float in [0, 1] representing retrieval priority in
  // Cortex's thermodynamic memory model. Non-tech users don't care
  // about the exact number — they want to know "is this active or
  // dormant?"
  //
  // Mapping aligned with thermodynamics.py's retrieval thresholds:
  //   ≥0.70 : Active  — frequently accessed / recently reinforced.
  //   ≥0.40 : Warm    — active in the last few days.
  //   ≥0.15 : Quiet   — not top-of-mind but still relevant.
  //   <0.15 : Dormant — fading; may be compressed or pruned soon.
  //
  // Eco + Feynman audit renamed from Hot/Warm/Cool/Cold — "Cold"
  // projected "broken/offline" and red Hot projected "CPU/error."
  function heatBadge(value) {
    var v = Number(value);
    if (isNaN(v)) return null;
    var pct = Math.max(0, Math.min(100, Math.round(v * 100)));
    var label, color;
    if (v >= 0.70)      { label = 'Active';  color = '#E08A50'; }
    else if (v >= 0.40) { label = 'Warm';    color = '#E0B040'; }
    else if (v >= 0.15) { label = 'Quiet';   color = '#70B0E0'; }
    else                { label = 'Dormant'; color = '#8090A0'; }
    return { label: label, color: color, pct: pct, value: v };
  }

  // ── Per-kind describers ──────────────────────────────────────────────
  // Dispatch table keeps plainDescription() small (Dijkstra §4.2).

  function _describeSymbol(n, name) {
    var sym = symbolTypeLabel(n.symbol_type) || 'Code item';
    var base = String(name).split('.').pop();
    var parent = String(name).indexOf('.') >= 0
      ? String(name).slice(0, String(name).lastIndexOf('.'))
      : null;
    var file = n.path ? String(n.path).split('/').pop() : null;
    var parts = [sym + ' named ' + base];
    if (parent) parts.push('inside ' + parent);
    if (file)   parts.push('in ' + file);
    return parts.join(', ') + '.';
  }

  function _describeFile(n, name) {
    var p = n.path ? String(n.path).split('/').pop() : name;
    var usage = primaryClusterLabel(n.primary_cluster);
    return 'File ' + p + (usage ? ' — ' + usage.toLowerCase() : '') + '.';
  }

  function _describeMemory(n) {
    var body = n.body ? String(n.body).split('\n')[0].slice(0, 140) : '';
    return body
      ? 'Cortex remembered: "' + body + '"'
      : 'A memory Cortex captured.';
  }

  function _describeDiscussion(n) {
    var msg = n.count || n.message_count;
    var parts = ['A conversation'];
    if (msg) parts.push('with ' + msg + ' message' + (msg === 1 ? '' : 's'));
    return parts.join(' ') + '.';
  }

  function _describeToolHub(n, name) {
    return 'A set of Claude tool uses grouped under ' + (n.tool || name) + '.';
  }

  function _describeDefault(n, name) {
    return kindIntro(n.kind) + (name ? ' — ' + name : '') + '.';
  }

  var _DESCRIBERS = {
    symbol:     _describeSymbol,
    file:       _describeFile,
    memory:     _describeMemory,
    discussion: _describeDiscussion,
    tool_hub:   _describeToolHub,
  };

  // Output is plain text (rendered via .textContent). No backticks —
  // they render literally as ASCII noise (Eco + Feynman audit).
  function plainDescription(n) {
    if (!n) return '';
    var name = n.label || n.id || '';
    var fn = _DESCRIBERS[n.kind] || _describeDefault;
    return fn(n, name);
  }

  // ── Export ──────────────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  window.JUG._wfgHumanize = {
    kindLabel:           kindLabel,
    kindIntro:           kindIntro,
    plainDescription:    plainDescription,
    stageLabel:          stageLabel,
    stageHint:           stageHint,
    symbolTypeLabel:     symbolTypeLabel,
    edgeVerb:            edgeVerb,
    prettyFieldKey:      prettyFieldKey,
    primaryClusterLabel: primaryClusterLabel,
    heatBadge:           heatBadge,
  };
})();
