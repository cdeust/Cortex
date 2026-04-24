// Cortex Workflow Graph — plain-language label tables.
//
// Extracted from workflow_graph_humanize.js (Dijkstra compliance pass:
// the humanize module exceeded the project 300-line rule; the label
// tables are pure data with no logic dependencies on the helper
// functions, so they factor out cleanly).
//
// Exports JUG._wfgLabels = {
//   KIND_LABELS, KIND_INTROS, SYMBOL_TYPE_LABELS,
//   STAGE_LABELS, STAGE_HINTS, EDGE_VERBS, FIELD_LABELS,
//   PRIMARY_CLUSTER_LABELS,
// };
//
// All label translations live here. The humanize module consumes this
// registry and exposes the higher-level helpers (kindLabel, stageLabel,
// plainDescription, heatBadge, etc.).

(function () {
  // ── Node kinds ───────────────────────────────────────────────────────
  var KIND_LABELS = {
    domain:     'Project',
    file:       'File',
    memory:     'Memory',
    discussion: 'Conversation',
    skill:      'Skill',
    hook:       'Automation',
    // Eco audit: "Helper" reads as a human (support contact / assistant
    // person). "Sub-assistant" is unambiguously AI/software.
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
  // Feynman audit: parenthetical definitions introduce further
  // undefined terms. Keep the short noun; raw type is in Technical.
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

  // ── Memory consolidation stages (cascade.py) ─────────────────────────
  // Feynman audit: "Just learned" attributes the learning to the USER —
  // wrong, Cortex captured it. "Stabilizing" (-izing verb) contradicts
  // LATE_LTP's near-permanent state. Corrected.
  var STAGE_LABELS = {
    labile:       'Newly captured',
    early_ltp:    'Forming',
    late_ltp:     'Well-held',
    consolidated: 'Solidly remembered',
  };

  var STAGE_HINTS = {
    labile:       'Fresh — still fragile, can be updated or forgotten easily.',
    early_ltp:    'Starting to stick. A few more recalls and it will stabilize.',
    late_ltp:     'Settled. It would take active forgetting to lose this.',
    consolidated: 'Baked in. This is part of the long-term picture.',
  };

  // ── Edge kinds — what the relationship means in English ──────────────
  // Eco audit: parenthetical jargon like "uses (calls)" contradicts the
  // lay-audience contract. Raw edge kind is in Technical details.
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

  // ── Field-key prettifiers (Advanced / Technical details section) ────
  // Eco audit: neuroscience vocabulary replaced with outcome-oriented
  // phrases; "(research)" tag marks fields only meaningful to
  // researchers so the Technical footer can de-emphasise them.
  var FIELD_LABELS = {
    domain_id:              'Project ID',
    session_id:             'Conversation ID',
    consolidation_stage:    'How settled it is',
    heat_base:              'Priority (raw)',
    arousal:                'Emotional intensity',
    emotional_valence:      'Emotional tone (−1 to 1)',
    dominant_emotion:       'Main emotion',
    importance:             'How important',
    surprise_score:         'How surprising',
    confidence:             'Confidence',
    access_count:           'Times accessed',
    useful_count:           'Times marked useful',
    replay_count:           'Times replayed',
    reconsolidation_count:  'Times updated',
    plasticity:             'How easily it changes (research)',
    stability:              'How hard to dislodge (research)',
    excitability:           'How readily it activates (research)',
    hippocampal_dependency: 'Still needs short-term memory (research)',
    schema_match_score:     'Fits a known pattern (score)',
    schema_id:              'Pattern it fits',
    separation_index:       'How unique among memories',
    interference_score:     'Conflicts with other memories',
    encoding_strength:      'How strongly recorded',
    decay_rate:             'Fading speed',
    decay_last_applied_at:  'Last faded',
    hours_in_stage:         'Hours in current state',
    stage_entered_at:       'Entered this state at',
    last_accessed:          'Last accessed',
    no_decay:               "Won't fade (pinned)",
    is_protected:           'Pinned',
    is_stale:               'File missing on disk',
    is_benchmark:           'Benchmark data',
    is_global:              'Available in every project',
    store_type:             'Storage kind',
    compression_level:      'Compression',
    compressed:             'Compressed',
    first_seen:             'First seen',
    last_modified:          'Last modified',
    primary_cluster:        'How it was used',
    symbol_type:            'Code-item type',
    qualified_name:         'Full name',
    extra_domain_ids:       'Also in projects',
    subagent_type:          'Sub-assistant type',
    created_at:             'Created',
    duration_ms:            'Duration',
    message_count:          'Messages',
    started_at:             'Started',
    last_activity:          'Last active',
    event:                  'Fires on event',
    signature:              'Signature',
    language:               'Language',
    line:                   'Line number',
    path:                   'File path',
    engram_id:              'Memory trace ID',
    dg_pattern_id:          'Distinct-pattern ID',
    pattern_separation_score: 'How unique (score)',
    cluster_id:             'Group ID',
    cluster_level:          'Zoom level (detail→summary)',
    valence_score:          'Emotional tone (−1 to 1)',
    arousal_score:          'Emotional intensity (0 to 1)',
    defined_line_start:     'Starts at line',
    defined_line_end:       'Ends at line',
  };

  // ── Primary-cluster (tool-use classification) labels ─────────────────
  // Feynman audit: edit_write previously collapsed create vs modify.
  var PRIMARY_CLUSTER_LABELS = {
    read_only:   'Read only',
    edit_write:  'Edited or created',
    search:      'Searched',
    run:         'Executed',
    mixed:       'Used in multiple ways',
  };

  // ── Export ──────────────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  window.JUG._wfgLabels = {
    KIND_LABELS:            KIND_LABELS,
    KIND_INTROS:            KIND_INTROS,
    SYMBOL_TYPE_LABELS:     SYMBOL_TYPE_LABELS,
    STAGE_LABELS:           STAGE_LABELS,
    STAGE_HINTS:            STAGE_HINTS,
    EDGE_VERBS:             EDGE_VERBS,
    FIELD_LABELS:           FIELD_LABELS,
    PRIMARY_CLUSTER_LABELS: PRIMARY_CLUSTER_LABELS,
  };
})();
