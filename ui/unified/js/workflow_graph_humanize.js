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
    agent:      'Helper',
    command:    'Slash command',
    tool_hub:   'Tool',
    symbol:     'Code item',
    entity:     'Thing mentioned',
    mcp:        'External tool',
  };

  // One-line intros used in the plain-language description sentence.
  var KIND_INTROS = {
    domain:     'a project Cortex is tracking',
    file:       'a file Claude worked on',
    memory:     'something Cortex decided was worth remembering',
    discussion: 'a conversation Claude had in this project',
    skill:      'a reusable skill Claude can invoke',
    hook:       'an automation that runs at specific moments',
    agent:      'a specialist helper Claude spawned',
    command:    'a slash command that was run',
    tool_hub:   'a group of related tools (read, edit, search, etc.)',
    symbol:     'a piece of code inside a file',
    entity:     'a thing (person, project, concept) mentioned across memories',
    mcp:        'an external tool Claude can call',
  };

  // ── Symbol sub-types ─────────────────────────────────────────────────
  var SYMBOL_TYPE_LABELS = {
    function:  'Function',
    method:    'Method (a function inside a class)',
    class:     'Class',
    interface: 'Interface',
    module:    'Module',
    constant:  'Constant',
    type:      'Type definition',
    protocol:  'Protocol',
    trait:     'Trait',
    enum:      'Enum (a set of named values)',
    struct:    'Struct (a data shape)',
  };

  // ── Memory consolidation stages (cascade.py) ────────────────────────
  // The backend uses neuroscience jargon (LABILE → EARLY_LTP → LATE_LTP
  // → CONSOLIDATED, after Kandel 2001). Translated to plain English.

  var STAGE_LABELS = {
    labile:        'Just learned',
    early_ltp:     'Forming',
    late_ltp:      'Stabilizing',
    consolidated: 'Solidly remembered',
  };

  var STAGE_HINTS = {
    labile:       'Fresh — still fragile, can be updated or forgotten easily.',
    early_ltp:    'Starting to stick. A few more recalls and it will stabilize.',
    late_ltp:     'Well-held. It would take active forgetting to lose this.',
    consolidated: 'Baked in. This is part of the long-term picture.',
  };

  // ── Edge kinds — what the relationship means in English ──────────────

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
    discussion_spawned_agent: 'called helper',
    discussion_ran_command:   'ran command',
    command_touched_file:     'touched file',
    invoked_mcp:              'called external tool',
    defined_in:               'lives in file',
    calls:                    'uses (calls)',
    imports:                  'brings in (imports)',
    member_of:                'belongs to',
  };

  // ── Field-key prettifiers (for the Advanced section) ────────────────

  var FIELD_LABELS = {
    domain_id:          'Project ID',
    session_id:         'Conversation ID',
    consolidation_stage: 'Memory stage',
    heat_base:          'Heat (raw)',
    arousal:            'Emotional arousal',
    emotional_valence:  'Emotional tone',
    dominant_emotion:   'Dominant emotion',
    importance:         'Importance score',
    surprise_score:     'Surprise score',
    confidence:         'Confidence',
    access_count:       'Times accessed',
    useful_count:       'Times marked useful',
    replay_count:       'Times replayed',
    reconsolidation_count: 'Times updated',
    plasticity:         'Plasticity',
    stability:          'Stability',
    excitability:       'Excitability',
    hippocampal_dependency: 'Hippocampal dependency',
    schema_match_score: 'Schema match',
    schema_id:          'Schema',
    separation_index:   'Distinctiveness',
    interference_score: 'Interference',
    encoding_strength:  'Encoding strength',
    hours_in_stage:     'Hours in current stage',
    stage_entered_at:   'Entered stage at',
    last_accessed:      'Last accessed',
    no_decay:           'Decay-proof',
    is_protected:       'Protected',
    is_stale:           'Stale',
    is_benchmark:       'Benchmark data',
    is_global:          'Global scope',
    store_type:         'Storage type',
    compression_level:  'Compression level',
    compressed:         'Compressed',
    first_seen:         'First seen',
    last_modified:      'Last modified',
    primary_cluster:    'Primary use',
    symbol_type:        'Code-item type',
    qualified_name:     'Full name',
    extra_domain_ids:   'Also in projects',
    subagent_type:      'Helper type',
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
  };

  // Primary-cluster (tool-use classification) labels.
  var PRIMARY_CLUSTER_LABELS = {
    read_only:   'Only read (never edited)',
    edit_write:  'Edited',
    search:      'Searched',
    run:         'Executed',
    mixed:       'Mixed use',
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
  function heatBadge(value) {
    var v = Number(value);
    if (isNaN(v)) return null;
    var pct = Math.max(0, Math.min(100, Math.round(v * 100)));
    var label, color;
    if (v >= 0.70)      { label = 'Hot';  color = '#E07070'; }
    else if (v >= 0.40) { label = 'Warm'; color = '#E0B040'; }
    else if (v >= 0.15) { label = 'Cool'; color = '#70B0E0'; }
    else                { label = 'Cold'; color = '#8090A0'; }
    return { label: label, color: color, pct: pct, value: v };
  }

  // Compose a one-sentence plain-language description of the node.
  // ``ctx`` is the graph context (byId, edges, adj, degree) passed to
  // the panel renderer so we can fetch e.g. the parent file of a symbol.
  function plainDescription(n, ctx) {
    if (!n) return '';
    var kind = n.kind;
    var name = n.label || n.id || '';

    // Symbol: "A method named `validate` that lives inside the `User` class in `auth.py`."
    if (kind === 'symbol') {
      var sym = symbolTypeLabel(n.symbol_type) || 'Code item';
      var base = String(name).split('.').pop();
      var parent = String(name).indexOf('.') >= 0
        ? String(name).slice(0, String(name).lastIndexOf('.'))
        : null;
      var file = n.path ? String(n.path).split('/').pop() : null;
      var parts = [sym + ' called `' + base + '`'];
      if (parent)
        parts.push('inside the `' + parent + '` class');
      if (file)
        parts.push('in ' + file);
      return parts.join(' ') + '.';
    }

    // File: "A file at mcp_server/core/thermodynamics.py, mostly edited this week."
    if (kind === 'file') {
      var p = n.path ? String(n.path).split('/').pop() : name;
      var usage = primaryClusterLabel(n.primary_cluster);
      return 'A file called `' + p + '`' +
        (usage ? ' — ' + usage.toLowerCase() : '') + '.';
    }

    // Memory: stage + first line of body.
    if (kind === 'memory') {
      var stg = stageLabel(n.stage);
      var body = n.body ? String(n.body).split('\n')[0].slice(0, 140) : '';
      var sent = 'A memory';
      if (stg) sent += ' (' + stg.toLowerCase() + ')';
      if (body) sent += ': "' + body + '"';
      else sent += '.';
      return sent;
    }

    // Discussion: session + message count + recency.
    if (kind === 'discussion') {
      var msg = (n.count || n.message_count);
      var parts2 = ['A conversation'];
      if (msg) parts2.push('with ' + msg + ' message' + (msg === 1 ? '' : 's'));
      return parts2.join(' ') + '.';
    }

    // Tool hub: "Group of tools for reading files — used 124 times on 18 files."
    if (kind === 'tool_hub') {
      return 'A group of related tools (' + (n.tool || name) + ').';
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
