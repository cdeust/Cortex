// Cortex Workflow Graph — plain-language humanization for the side panel.
//
// The raw node data the backend emits uses technical vocabulary (kind="symbol",
// stage="EARLY_LTP", heat=0.534, symbol_type="function"). Non-technical users
// look at that and see an opaque data dump. This module translates every raw
// field into everyday English while preserving the original value behind an
// "Advanced" expander for power users.
//
// Exports JUG._wfgHumanize = {
//   kindLabel(kind)          -> "Function or class" style label
//   kindIntro(kind)          -> one-line "what is this" sentence fragment
//   plainDescription(n, ctx) -> full sentence describing the node
//   stageLabel(stage)        -> "Just learned" etc.
//   stageHint(stage)         -> one-line explanation
//   heatBadge(value)         -> { label, color, pct } — visual signal
//   symbolTypeLabel(type)    -> "Method on a class" etc.
//   edgeVerb(kind)           -> "uses", "belongs to", etc.
//   prettyFieldKey(raw)      -> "First seen" instead of "first_seen"
// };
//
// Pure presentation logic — no DOM, no side effects. The panel imports
// these and composes the DOM.

(function () {
  // ── Node kinds ───────────────────────────────────────────────────────
  // Maps the internal "kind" string to a label users understand. The
  // mapping is deliberately plain-language. Technical users can still
  // see the raw kind in the Advanced section.

  var KIND_LABELS = {
    domain:     'Project',
    file:       'File',
    memory:     'Memory',
    discussion: 'Conversation',
    skill:      'Skill',
    hook:       'Automation',
    // Eco audit: "Helper" reads as a human (support contact / assistant
    // person). Use "Sub-assistant" to block that wrong reading — it is
    // unambiguously an AI/software construct.
    agent:      'Sub-assistant',
    command:    'Slash command',
    tool_hub:   'Tool group',
    symbol:     'Code item',
    entity:     'Thing mentioned',
    mcp:        'External tool',
  };

  // One-line intros used in the plain-language description sentence.
  var KIND_INTROS = {
    domain:     'a project Cortex is tracking',
    file:       'a file Claude worked on',
    memory:     'something Cortex stored for later',
    discussion: 'a conversation Claude had in this project',
    skill:      'a reusable skill Claude can invoke',
    hook:       'an automation that runs at specific moments',
    agent:      'a sub-assistant Claude spawned to help with a task',
    command:    'a slash command that was run',
    tool_hub:   'a group of related tools Claude used',
    symbol:     'a piece of code inside a file',
    entity:     'something mentioned across memories',
    mcp:        'an external tool Claude can call',
  };

  // ── Symbol sub-types ─────────────────────────────────────────────────
  // Feynman audit: parenthetical definitions ("Method (a function inside
  // a class)", "Enum (a set of named values)") introduce further
  // undefined terms to define the first. Net jargon delta is positive.
  // Keep the short noun; the Technical details footer carries the raw
  // type code if a reader needs to dig.
  var SYMBOL_TYPE_LABELS = {
    function:  'Function',
    method:    'Method',
    class:     'Class',
    interface: 'Interface',
    module:    'Module',
    constant:  'Constant',
    type:      'Type definition',
    protocol:  'Protocol',
    trait:     'Trait',
    enum:      'Enum',
    struct:    'Struct',
  };

  // ── Memory consolidation stages (cascade.py) ────────────────────────
  // The backend uses neuroscience jargon (LABILE → EARLY_LTP → LATE_LTP
  // → CONSOLIDATED, after Kandel 2001). Translated to plain English.

  // Feynman audit: "Just learned" attributes the learning to the USER,
  // which is wrong — Cortex captured it. "Stabilizing" contradicts the
  // LATE_LTP state (near-permanent) by using an -izing verb. Both
  // corrected to match the hint text semantics.
  var STAGE_LABELS = {
    labile:        'Newly captured',
    early_ltp:     'Forming',
    late_ltp:      'Well-held',
    consolidated: 'Solidly remembered',
  };

  var STAGE_HINTS = {
    labile:       'Fresh — still fragile, can be updated or forgotten easily.',
    early_ltp:    'Starting to stick. A few more recalls and it will stabilize.',
    late_ltp:     'Settled. It would take active forgetting to lose this.',
    consolidated: 'Baked in. This is part of the long-term picture.',
  };

  // ── Edge kinds — what the relationship means in English ──────────────

  // Eco audit: parenthetical jargon ("uses (calls)", "brings in (imports)")
  // contradicts the lay-audience contract. Keep only the plain verb here;
  // the raw edge kind is visible in Technical details.
  var EDGE_VERBS = {
    in_domain:                'belongs to',
    tool_used_file:           'edited with',
    command_in_hub:           'is part of',
    invoked_skill:            'used the skill',
    triggered_hook:           'triggered',
    spawned_agent:            'called in',
    about_entity:             'is about',
    discussion_touched_file:  'worked on file',
    discussion_used_tool:     'used tool',
    discussion_spawned_agent: 'called sub-assistant',
    discussion_ran_command:   'ran command',
    command_touched_file:     'touched file',
    invoked_mcp:              'called external tool',
    defined_in:               'lives in file',
    calls:                    'uses',
    imports:                  'brings in',
    member_of:                'belongs to',
  };

  // ── Field-key prettifiers (for the Advanced section) ────────────────

  // Eco audit: the previous table spoke Neuroscience vocabulary
  // (Hippocampal dependency, Plasticity, Encoding strength, Schema
  // match, Interference) in a panel advertised to non-tech users.
  // Translated to outcome-oriented phrases a PM can read. Where a field
  // is genuinely only meaningful to a researcher, the entry is marked
  // with a research-only prefix so the collapsible Technical details
  // footer can visually de-emphasise them.
  var FIELD_LABELS = {
    domain_id:          'Project ID',
    session_id:         'Conversation ID',
    consolidation_stage: 'How settled it is',
    heat_base:          'Priority (raw)',
    arousal:            'Emotional intensity',
    emotional_valence:  'Emotional tone (−1 to 1)',
    dominant_emotion:   'Main emotion',
    importance:         'How important',
    surprise_score:     'How surprising',
    confidence:         'Confidence',
    access_count:       'Times accessed',
    useful_count:       'Times marked useful',
    replay_count:       'Times replayed',
    reconsolidation_count: 'Times updated',
    plasticity:         'How easily it changes (research)',
    stability:          'How hard to dislodge (research)',
    excitability:       'How readily it activates (research)',
    hippocampal_dependency: 'Still needs short-term memory (research)',
    schema_match_score: 'Fits a known pattern (score)',
    schema_id:          'Pattern it fits',
    separation_index:   'How unique among memories',
    interference_score: 'Conflicts with other memories',
    encoding_strength:  'How strongly recorded',
    decay_rate:         'Fading speed',
    decay_last_applied_at: 'Last faded',
    hours_in_stage:     'Hours in current state',
    stage_entered_at:   'Entered this state at',
    last_accessed:      'Last accessed',
    no_decay:           "Won't fade (pinned)",
    is_protected:       'Pinned',
    is_stale:           'File missing on disk',
    is_benchmark:       'Benchmark data',
    is_global:          'Available in every project',
    store_type:         'Storage kind',
    compression_level:  'Compression',
    compressed:         'Compressed',
    first_seen:         'First seen',
    last_modified:      'Last modified',
    primary_cluster:    'How it was used',
    symbol_type:        'Code-item type',
    qualified_name:     'Full name',
    extra_domain_ids:   'Also in projects',
    subagent_type:      'Sub-assistant type',
    created_at:         'Created',
    duration_ms:        'Duration',
    message_count:      'Messages',
    started_at:         'Started',
    last_activity:      'Last active',
    event:              'Fires on event',
    signature:          'Signature',
    language:           'Language',
    line:               'Line number',
    path:               'File path',
    engram_id:          'Memory trace ID',
    dg_pattern_id:      'Distinct-pattern ID',
    pattern_separation_score: 'How unique (score)',
    cluster_id:         'Group ID',
    cluster_level:      'Zoom level (detail→summary)',
    valence_score:      'Emotional tone (−1 to 1)',
    arousal_score:      'Emotional intensity (0 to 1)',
    defined_line_start: 'Starts at line',
    defined_line_end:   'Ends at line',
  };

  // Feynman audit: edit_write collapsed "created" and "modified". Keep
  // one label but make it accurate ("Edited or created"). Eco: "Only
  // read (never edited)" was accurate but verbose — "Read only" reads
  // the same and takes half the width.
  var PRIMARY_CLUSTER_LABELS = {
    read_only:   'Read only',
    edit_write:  'Edited or created',
    search:      'Searched',
    run:         'Executed',
    mixed:       'Used in multiple ways',
  };

  // ── Public helpers ──────────────────────────────────────────────────

  function kindLabel(kind)  { return KIND_LABELS[kind]  || kind || 'Item'; }
  function kindIntro(kind)  { return KIND_INTROS[kind]  || 'an item Cortex tracked'; }

  function stageLabel(stage) {
    if (!stage) return null;
    var key = String(stage).toLowerCase();
    return STAGE_LABELS[key] || stage;
  }

  function stageHint(stage) {
    if (!stage) return null;
    var key = String(stage).toLowerCase();
    return STAGE_HINTS[key] || null;
  }

  function symbolTypeLabel(type) {
    if (!type) return null;
    return SYMBOL_TYPE_LABELS[String(type).toLowerCase()] || type;
  }

  function edgeVerb(kind) {
    return EDGE_VERBS[kind] || kind || 'relates to';
  }

  // Human-readable key for a raw field name. ``first_seen`` → "First seen".
  // Falls back to the raw key when we don't have a translation.
  function prettyFieldKey(raw) {
    if (!raw) return '';
    if (FIELD_LABELS[raw]) return FIELD_LABELS[raw];
    return String(raw).replace(/_/g, ' ').replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function primaryClusterLabel(raw) {
    if (!raw) return null;
    return PRIMARY_CLUSTER_LABELS[String(raw).toLowerCase()] || raw;
  }

  // Heat is a float in [0, 1] representing how "active" something is in
  // Cortex's thermodynamic memory model. Non-tech users don't care about
  // the exact number — they want to know "is this hot or cold?"
  //
  // Mapping aligned with thermodynamics.py's retrieval thresholds:
  //   ≥0.70 : Hot    — frequently accessed / recently reinforced.
  //   ≥0.40 : Warm   — active in the last few days.
  //   ≥0.15 : Cool   — not top-of-mind but still relevant.
  //   <0.15 : Cold   — fading; may be compressed or pruned soon.
  // Eco + Feynman audit:
  //   - "Cold" projects "broken / offline / unavailable". Real meaning:
  //     faded but intact. Rename to "Dormant".
  //   - "Hot" + red projects "danger / error / CPU overload". Rename
  //     the hottest band to "Active" with amber-red.
  //   - The % should read as "priority" not "activity level" — the
  //     value is retrieval priority, not CPU activity.
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

  // Compose a one-sentence plain-language description of the node.
  // ``ctx`` is the graph context (byId, edges, adj, degree) passed to
  // the panel renderer so we can fetch e.g. the parent file of a symbol.
  // Output is plain text (rendered via .textContent). Backticks used to
  // frame identifiers get rendered literally and look like stray ASCII
  // noise to non-tech readers (Eco + Feynman audit). We drop them and
  // use plain quotes where disambiguation helps. The previous ``ctx``
  // parameter was dead (Dijkstra §9 audit) and has been removed.
  function plainDescription(n) {
    if (!n) return '';
    var kind = n.kind;
    var name = n.label || n.id || '';

    // Symbol: "Method named bar, inside the Foo class, in auth.py."
    if (kind === 'symbol') {
      var sym = symbolTypeLabel(n.symbol_type) || 'Code item';
      var base = String(name).split('.').pop();
      var parent = String(name).indexOf('.') >= 0
        ? String(name).slice(0, String(name).lastIndexOf('.'))
        : null;
      var file = n.path ? String(n.path).split('/').pop() : null;
      var parts = [sym + ' named ' + base];
      if (parent)
        parts.push('inside ' + parent);
      if (file)
        parts.push('in ' + file);
      return parts.join(', ') + '.';
    }

    // File: "File cascade.py — edited or created."
    if (kind === 'file') {
      var p = n.path ? String(n.path).split('/').pop() : name;
      var usage = primaryClusterLabel(n.primary_cluster);
      return 'File ' + p + (usage ? ' — ' + usage.toLowerCase() : '') + '.';
    }

    // Memory: first line of what's stored; stage rendered as the row
    // label above, not inline in the sentence (Feynman: lowercase
    // inlined stage reads as a verb phrase).
    if (kind === 'memory') {
      var body = n.body ? String(n.body).split('\n')[0].slice(0, 140) : '';
      if (body) return 'Cortex remembered: "' + body + '"';
      return 'A memory Cortex captured.';
    }

    // Discussion: session + message count.
    if (kind === 'discussion') {
      var msg = (n.count || n.message_count);
      var parts2 = ['A conversation'];
      if (msg) parts2.push('with ' + msg + ' message' + (msg === 1 ? '' : 's'));
      return parts2.join(' ') + '.';
    }

    // Tool hub: name alone is cleaner than "a group of related tools (Read)"
    // which misleads when the label is singular (Feynman).
    if (kind === 'tool_hub') {
      return 'A set of Claude tool uses grouped under ' + (n.tool || name) + '.';
    }

    // Skill, Hook, Agent, Command, Domain: simple intro + name.
    return kindIntro(kind) + (name ? ' — ' + name : '') + '.';
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
