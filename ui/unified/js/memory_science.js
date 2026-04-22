// Cortex — Memory Science Panel
// Renders every scientific measurement Cortex tracks per memory as a
// compact labelled grid. Used by both the Knowledge card and the Board
// (Kanban) card so the two views stay consistent and any new instrument
// added to the memory table surfaces in both places at once.
//
// Conventions:
//   * Reads fields in both snake_case (native) and camelCase (legacy
//     alias) so the layer stays robust across schema drift.
//   * Falls back silently when a field is absent — memories written
//     before a given instrument existed remain renderable.
//   * Numeric values get a tiny progress bar proportional to their
//     canonical 0..1 range. Counters are printed raw. Timestamps are
//     rendered as "Nd ago" / "Nh ago" / "Nm ago".
(function () {
  var JUG = window.JUG = window.JUG || {};

  // Canonical field-descriptor list. Order here IS the display order.
  // Each entry: { keys: [snake, camel], label, kind, range, unit }.
  //   kind ∈ "bar"|"count"|"pct"|"flag"|"text"|"age"
  //   range only meaningful for "bar" and "pct".
  var FIELDS = [
    { keys: ["heat"],                   label: "Heat",          kind: "bar",  range: [0, 1] },
    { keys: ["heat_base", "heatBase"],  label: "Heat base",     kind: "bar",  range: [0, 1] },
    { keys: ["importance"],             label: "Importance",    kind: "bar",  range: [0, 1] },
    { keys: ["surprise_score", "surpriseScore"], label: "Surprise", kind: "bar", range: [0, 1] },
    { keys: ["emotional_valence", "emotionalValence"], label: "Valence", kind: "bipolar", range: [-1, 1] },
    { keys: ["arousal"],                label: "Arousal",       kind: "bar",  range: [0, 1] },
    { keys: ["confidence"],             label: "Confidence",    kind: "bar",  range: [0, 1] },
    { keys: ["plasticity"],             label: "Plasticity",    kind: "bar",  range: [0, 1] },
    { keys: ["stability"],              label: "Stability",     kind: "bar",  range: [0, 1] },
    { keys: ["excitability"],           label: "Excitability",  kind: "bar",  range: [0, 1] },
    { keys: ["hippocampal_dependency", "hippocampalDependency"], label: "Hippo-dep", kind: "bar", range: [0, 1] },
    { keys: ["encoding_strength", "encodingStrength"], label: "Encoding", kind: "bar", range: [0, 1] },
    { keys: ["separation_index", "separationIndex"],   label: "Separation", kind: "bar", range: [0, 1] },
    { keys: ["interference_score", "interferenceScore"], label: "Interference", kind: "bar", range: [0, 1] },
    { keys: ["schema_match_score", "schemaMatchScore"], label: "Schema match", kind: "bar", range: [0, 1] },
    { keys: ["access_count", "accessCount"],     label: "Access",   kind: "count" },
    { keys: ["useful_count", "usefulCount"],     label: "Useful",   kind: "count" },
    { keys: ["replay_count", "replayCount"],     label: "Replays",  kind: "count" },
    { keys: ["reconsolidation_count", "reconsolidationCount"], label: "Reconsol", kind: "count" },
    { keys: ["hours_in_stage", "hoursInStage"],  label: "In stage", kind: "count", unit: "h" },
    { keys: ["compression_level", "compressionLevel"], label: "Compression", kind: "count" },
    { keys: ["dominant_emotion", "dominantEmotion"],  label: "Emotion",  kind: "text" },
    { keys: ["store_type", "storeType"],         label: "Store",    kind: "text" },
    { keys: ["schema_id", "schemaId"],           label: "Schema",   kind: "text" },
    { keys: ["is_protected", "isProtected"],     label: "Protected", kind: "flag" },
    { keys: ["no_decay", "noDecay"],             label: "No-decay",  kind: "flag" },
    { keys: ["is_stale", "isStale"],             label: "Stale",     kind: "flag" },
    { keys: ["is_benchmark", "isBenchmark"],     label: "Benchmark", kind: "flag" },
    { keys: ["is_global", "isGlobal"],           label: "Global",    kind: "flag" },
    { keys: ["stage_entered_at", "stageEnteredAt"], label: "Stage age", kind: "age" },
    { keys: ["last_accessed", "lastAccessed"],   label: "Accessed",  kind: "age" },
    { keys: ["created_at", "createdAt"],         label: "Created",   kind: "age" },
  ];

  function pick(mem, keys) {
    for (var i = 0; i < keys.length; i++) {
      var v = mem[keys[i]];
      if (v !== undefined && v !== null) return v;
    }
    return undefined;
  }

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  function fmtNum(v) {
    var n = Number(v);
    if (!isFinite(n)) return String(v);
    if (Math.abs(n) >= 100) return n.toFixed(0);
    if (Math.abs(n) >= 10)  return n.toFixed(1);
    return n.toFixed(2);
  }

  function fmtAge(iso) {
    if (!iso) return null;
    var t = Date.parse(iso);
    if (isNaN(t)) return null;
    var delta = (Date.now() - t) / 1000;
    if (delta < 60) return Math.round(delta) + "s";
    if (delta < 3600) return Math.round(delta / 60) + "m";
    if (delta < 86400) return Math.round(delta / 3600) + "h";
    if (delta < 86400 * 30) return Math.round(delta / 86400) + "d";
    return Math.round(delta / 86400 / 30) + "mo";
  }

  // ── Row factories — one per kind ────────────────────────────────

  function rowShell(label) {
    var row = document.createElement("div");
    row.className = "ms-row";
    var k = document.createElement("span");
    k.className = "ms-k";
    k.textContent = label;
    row.appendChild(k);
    return row;
  }

  function appendBarRow(wrap, label, v, range) {
    if (v === undefined) return;
    var n = Number(v);
    if (!isFinite(n)) return;
    var lo = range[0], hi = range[1];
    var pct = hi === lo ? 0 : clamp01((n - lo) / (hi - lo));
    var row = rowShell(label);
    var bar = document.createElement("span");
    bar.className = "ms-bar";
    var fill = document.createElement("span");
    fill.className = "ms-bar-fill";
    fill.style.width = (pct * 100).toFixed(0) + "%";
    bar.appendChild(fill);
    row.appendChild(bar);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-num";
    val.textContent = fmtNum(n);
    row.appendChild(val);
    wrap.appendChild(row);
  }

  function appendBipolarRow(wrap, label, v, range) {
    if (v === undefined) return;
    var n = Number(v);
    if (!isFinite(n)) return;
    var pct = clamp01((n - range[0]) / (range[1] - range[0]));  // 0..1 with 0.5 = neutral
    var row = rowShell(label);
    var bar = document.createElement("span");
    bar.className = "ms-bar ms-bar-bipolar";
    var marker = document.createElement("span");
    marker.className = "ms-bar-marker";
    marker.style.left = (pct * 100).toFixed(0) + "%";
    bar.appendChild(marker);
    row.appendChild(bar);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-num";
    val.textContent = (n > 0 ? "+" : "") + fmtNum(n);
    row.appendChild(val);
    wrap.appendChild(row);
  }

  function appendCountRow(wrap, label, v, unit) {
    if (v === undefined || v === null) return;
    var n = Number(v);
    if (!isFinite(n) || n === 0) return;  // drop zeros
    var row = rowShell(label);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-count";
    val.textContent = fmtNum(n) + (unit || "");
    row.appendChild(val);
    wrap.appendChild(row);
  }

  function appendTextRow(wrap, label, v) {
    if (v === undefined || v === null || v === "") return;
    var s = String(v);
    if (!s.trim()) return;
    var row = rowShell(label);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-text";
    val.textContent = s;
    row.appendChild(val);
    wrap.appendChild(row);
  }

  function appendFlagRow(wrap, label, v) {
    if (!v) return;  // only render when true
    var row = rowShell(label);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-flag";
    val.textContent = "✓";
    row.appendChild(val);
    wrap.appendChild(row);
  }

  function appendAgeRow(wrap, label, v) {
    var age = fmtAge(v);
    if (!age) return;
    var row = rowShell(label);
    var val = document.createElement("span");
    val.className = "ms-v ms-v-age";
    val.textContent = age + " ago";
    row.appendChild(val);
    wrap.appendChild(row);
  }

  // ── Emotion + Meaning prominent chips ───────────────────────────
  // These two dimensions are the first thing a reader cares about when
  // scanning a memory; burying them in the measurement grid hides the
  // signal. We surface them as separate chips above the grid.

  var EMOTION_COLORS = {
    urgency:      "#EF4444",  // red
    frustration:  "#F59E0B",  // amber
    satisfaction: "#10B981",  // emerald
    discovery:    "#60A5FA",  // sky
    confusion:    "#A78BFA",  // violet
    neutral:      "#9CA3AF",  // slate
    joy:          "#FCD34D",
    fear:         "#F472B6",
    surprise:     "#06B6D4",
    anger:        "#DC2626",
    sadness:      "#3B82F6",
    disgust:      "#84CC16",
  };

  function buildEmotionChip(mem) {
    var emo = pick(mem, ["dominant_emotion", "dominantEmotion", "emotion"]);
    var valence = pick(mem, ["emotional_valence", "emotionalValence"]);
    var arousal = pick(mem, ["arousal"]);
    if (!emo && valence === undefined && arousal === undefined) return null;

    var chip = document.createElement("div");
    chip.className = "ms-emotion";

    var label = String(emo || "neutral").toLowerCase();
    var color = EMOTION_COLORS[label] || "#9CA3AF";

    var dot = document.createElement("span");
    dot.className = "ms-emotion-dot";
    dot.style.background = color;
    chip.appendChild(dot);

    var name = document.createElement("span");
    name.className = "ms-emotion-name";
    name.textContent = label;
    name.style.color = color;
    chip.appendChild(name);

    if (valence !== undefined && valence !== null) {
      var v = Number(valence);
      if (isFinite(v)) {
        var val = document.createElement("span");
        val.className = "ms-emotion-val";
        val.textContent = (v > 0 ? "↑" : v < 0 ? "↓" : "◦")
          + " " + fmtNum(Math.abs(v));
        val.title = "valence";
        chip.appendChild(val);
      }
    }
    if (arousal !== undefined && arousal !== null) {
      var ar = Number(arousal);
      if (isFinite(ar)) {
        var arEl = document.createElement("span");
        arEl.className = "ms-emotion-arousal";
        arEl.textContent = "⚡ " + fmtNum(ar);
        arEl.title = "arousal";
        chip.appendChild(arEl);
      }
    }
    return chip;
  }

  // Build a "Meaning" section — the semantic layer: what this memory
  // MEANS relative to the system's schemas, stores, and tags. Distinct
  // from the raw content preview above it.
  function buildMeaningSection(mem) {
    var store = pick(mem, ["store_type", "storeType"]);
    var schemaId = pick(mem, ["schema_id", "schemaId"]);
    var schemaMatch = pick(mem, ["schema_match_score", "schemaMatchScore"]);
    var tags = mem.tags || [];
    var body = mem.body || mem.content || "";

    var hasAny = store || schemaId
      || (schemaMatch !== undefined && schemaMatch !== null && Number(schemaMatch) > 0)
      || (tags && tags.length);
    if (!hasAny) return null;

    var section = document.createElement("div");
    section.className = "ms-meaning";

    var header = document.createElement("div");
    header.className = "ms-meaning-header";
    header.textContent = "Meaning";
    section.appendChild(header);

    var grid = document.createElement("div");
    grid.className = "ms-meaning-grid";

    // Store type — episodic (experience) vs semantic (knowledge).
    if (store) {
      var storeRow = document.createElement("div");
      storeRow.className = "ms-meaning-row";
      var storeIcon = document.createElement("span");
      storeIcon.className = "ms-meaning-icon ms-meaning-store-" + String(store).toLowerCase();
      storeIcon.textContent = store === "semantic" ? "◆" : "●";
      var storeLabel = document.createElement("span");
      storeLabel.className = "ms-meaning-label";
      storeLabel.textContent = store === "semantic" ? "Knowledge (semantic)" : "Experience (episodic)";
      storeRow.appendChild(storeIcon);
      storeRow.appendChild(storeLabel);
      grid.appendChild(storeRow);
    }

    // Schema alignment.
    if (schemaId) {
      var schemaRow = document.createElement("div");
      schemaRow.className = "ms-meaning-row";
      var icon = document.createElement("span");
      icon.className = "ms-meaning-icon ms-meaning-schema";
      icon.textContent = "⌬";
      var lbl = document.createElement("span");
      lbl.className = "ms-meaning-label";
      var match = Number(schemaMatch || 0);
      lbl.textContent = "Schema · " + schemaId
        + (match > 0 ? " · " + Math.round(match * 100) + "% match" : "");
      schemaRow.appendChild(icon);
      schemaRow.appendChild(lbl);
      grid.appendChild(schemaRow);
    }

    // Tag-derived meaning categories. Filter to the meaningful ones
    // (drop auto-captured noise tags).
    var meaningTags = (tags || []).filter(function (t) {
      var s = String(t).toLowerCase();
      return s !== "auto-captured"
        && !s.startsWith("_")
        && !s.startsWith("tool:")
        && !s.startsWith("project:");
    });
    if (meaningTags.length) {
      var tagRow = document.createElement("div");
      tagRow.className = "ms-meaning-row ms-meaning-tags-row";
      var tIcon = document.createElement("span");
      tIcon.className = "ms-meaning-icon ms-meaning-tags";
      tIcon.textContent = "#";
      tagRow.appendChild(tIcon);
      var tagsWrap = document.createElement("span");
      tagsWrap.className = "ms-meaning-tags-wrap";
      meaningTags.slice(0, 8).forEach(function (t) {
        var chip = document.createElement("span");
        chip.className = "ms-meaning-tag";
        chip.textContent = String(t);
        tagsWrap.appendChild(chip);
      });
      tagRow.appendChild(tagsWrap);
      grid.appendChild(tagRow);
    }

    // Gist: first meaningful line of the body, stripped of tool-capture
    // boilerplate. This gives the reader a "what it meant" anchor.
    var gist = extractGist(body);
    if (gist) {
      var gistRow = document.createElement("div");
      gistRow.className = "ms-meaning-row ms-meaning-gist-row";
      var gIcon = document.createElement("span");
      gIcon.className = "ms-meaning-icon ms-meaning-gist";
      gIcon.textContent = "“";
      var gText = document.createElement("span");
      gText.className = "ms-meaning-gist-text";
      gText.textContent = gist;
      gistRow.appendChild(gIcon);
      gistRow.appendChild(gText);
      grid.appendChild(gistRow);
    }

    section.appendChild(grid);
    return section;
  }

  // Extract the first non-boilerplate line of a memory body — the
  // shortest textual handle on what the memory is about.
  function extractGist(body) {
    if (!body) return "";
    var lines = String(body).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i].trim();
      if (!ln) continue;
      // Drop the standard post_tool_capture prefixes.
      if (ln.startsWith("# Tool:")) continue;
      if (ln.startsWith("**Command:**")) continue;
      if (ln.startsWith("**File:**")) continue;
      if (ln.startsWith("**Read:**")) continue;
      if (ln.startsWith("**Output:**")) continue;
      if (ln.startsWith("```")) continue;
      if (ln.length < 8) continue;
      // Truncate for card display.
      return ln.length > 240 ? ln.slice(0, 240) + "…" : ln;
    }
    return "";
  }

  // ── Public API ──────────────────────────────────────────────────

  // Build a full panel — every field present on `mem` gets rendered.
  // The caller supplies `variant`:
  //   "full"    — every row, no truncation           (Knowledge card)
  //   "compact" — drop bipolar/text/age + less common fields (Board card)
  function buildSciencePanel(mem, variant) {
    if (!mem) return null;
    var wrap = document.createElement("div");
    wrap.className = "ms-panel" + (variant === "compact" ? " ms-panel-compact" : "");

    var limit = variant === "compact" ? 6 : FIELDS.length;
    var printed = 0;
    for (var i = 0; i < FIELDS.length && printed < limit; i++) {
      var f = FIELDS[i];
      var v = pick(mem, f.keys);
      if (v === undefined || v === null) continue;
      // In compact mode, hide text/age/flag-unless-protected to keep the
      // card dense. Always keep bars + counts which carry the signal.
      if (variant === "compact") {
        if (f.kind === "text" || f.kind === "age") continue;
        if (f.kind === "flag" && f.label !== "Protected" && f.label !== "No-decay") continue;
      }
      var before = wrap.childElementCount;
      if (f.kind === "bar")      appendBarRow(wrap, f.label, v, f.range);
      else if (f.kind === "bipolar") appendBipolarRow(wrap, f.label, v, f.range);
      else if (f.kind === "count")   appendCountRow(wrap, f.label, v, f.unit);
      else if (f.kind === "pct")     appendBarRow(wrap, f.label, v, [0, 1]);
      else if (f.kind === "text")    appendTextRow(wrap, f.label, v);
      else if (f.kind === "flag")    appendFlagRow(wrap, f.label, v);
      else if (f.kind === "age")     appendAgeRow(wrap, f.label, v);
      if (wrap.childElementCount > before) printed++;
    }
    return wrap.childElementCount ? wrap : null;
  }

  // ── Explained panel (for detail modals) ─────────────────────────
  // Same fields as buildSciencePanel, but each row gets a plain-English
  // one-sentence explanation so a non-technical reader can grasp the
  // number without a neuroscience glossary. Designed for the detail
  // modal (openExpanded in knowledge.js), where real estate is generous.
  //
  // Explanations intentionally avoid jargon: no "LTP", no "synaptic",
  // no Greek letters. They describe the PRACTICAL effect of the value.

  var EXPLAIN = {
    heat: "How active this memory is right now. Hot means it was used recently; Cold means it's drifting toward being forgotten.",
    heat_base: "The underlying activity level before today's decay is applied. Think of it as the memory's baseline temperature.",
    importance: "How much Cortex judges this memory matters. High importance means keep it forever; low means it's disposable.",
    surprise_score: "How unexpected this memory was when it arrived. Surprises stick in the mind better than routine events.",
    emotional_valence: "The emotional tone of the memory. Positive feelings score above zero, negative below, neutral at the midline.",
    arousal: "How intensely emotional this memory is, regardless of direction. Urgent or vivid events score high.",
    confidence: "How certain Cortex is about what this memory says. Low confidence means the content may be partly speculation.",
    plasticity: "How easily this memory can still change. Fresh memories are plastic; old well-worn ones stiffen into final shape.",
    stability: "How resistant this memory is to being overwritten or forgotten. Stable memories survive competing information.",
    excitability: "How easily this memory gets pulled into related thinking. High excitability means it primes nearby memories.",
    hippocampal_dependency: "How much this memory still depends on fast, fragile short-term storage. It drops toward zero as the memory moves into permanent storage.",
    encoding_strength: "How cleanly the memory was written down the first time. Weak encoding produces blurry or incomplete recall.",
    separation_index: "How distinct this memory is from its neighbours. Well-separated memories don't blur into each other.",
    interference_score: "How much nearby memories are competing with this one. High interference makes recall harder.",
    schema_match_score: "How well this memory fits an existing mental structure. Higher match means easier to integrate with what's already known.",
    access_count: "How many times you've pulled this memory up. Each access reinforces it a little.",
    useful_count: "How many times you confirmed this memory was useful when it came back. Direct feedback that keeps it alive.",
    replay_count: "How many sleep-like replay cycles have rehearsed this memory. Replay is how the system moves it from short-term to long-term storage.",
    reconsolidation_count: "How many times this memory has been modified on retrieval. Every recall is a chance to update or correct it.",
    hours_in_stage: "How long the memory has sat in its current consolidation stage. Long stays can indicate it's stuck.",
    compression_level: "How much the original content has been summarised into a gist. Zero means full original text.",
    dominant_emotion: "Which emotional category best describes the content: urgency, frustration, satisfaction, discovery, confusion, etc.",
    store_type: "Episodic = a specific experience (what happened). Semantic = extracted general knowledge (what it means).",
    schema_id: "The name of the knowledge structure this memory has been slotted into.",
    is_protected: "Marked as must-keep. The decay and eviction processes skip over this memory.",
    no_decay: "Exempt from the normal cooling process. Usually used for benchmark fixtures or explicit anchors.",
    is_stale: "Flagged as outdated. The content no longer matches reality and should be refreshed or retired.",
    is_benchmark: "Loaded as part of an evaluation test set, not from everyday work.",
    is_global: "Applies across every project, not just one domain. Cortex carries it everywhere.",
    stage_entered_at: "When the memory most recently moved into its current consolidation stage.",
    last_accessed: "The last time this memory was recalled or referenced.",
    created_at: "When Cortex first wrote this memory down.",
    stage: "Where this memory sits in the consolidation pipeline: New, Growing, Strong, Stable, or Updating.",
  };

  // Short human label for each field — matches EXPLAIN keys.
  var FRIENDLY_LABEL = {
    heat: "Activity (heat)",
    heat_base: "Baseline activity",
    importance: "Importance",
    surprise_score: "Surprise",
    emotional_valence: "Emotional tone",
    arousal: "Emotional intensity",
    confidence: "Confidence",
    plasticity: "Plasticity",
    stability: "Stability",
    excitability: "Excitability",
    hippocampal_dependency: "Short-term dependency",
    encoding_strength: "Encoding strength",
    separation_index: "Distinctness",
    interference_score: "Interference",
    schema_match_score: "Schema match",
    access_count: "Times recalled",
    useful_count: "Times useful",
    replay_count: "Sleep replays",
    reconsolidation_count: "Updates on recall",
    hours_in_stage: "Hours in current stage",
    compression_level: "Compression level",
    dominant_emotion: "Dominant emotion",
    store_type: "Memory store",
    schema_id: "Knowledge schema",
    is_protected: "Protected",
    no_decay: "Exempt from decay",
    is_stale: "Marked stale",
    is_benchmark: "Benchmark fixture",
    is_global: "Global (all projects)",
    stage_entered_at: "Entered current stage",
    last_accessed: "Last accessed",
    created_at: "Created",
    stage: "Consolidation stage",
  };

  function buildExplainedPanel(mem) {
    if (!mem) return null;
    var wrap = document.createElement("div");
    wrap.className = "ms-explain";

    var header = document.createElement("div");
    header.className = "ms-explain-header";
    header.textContent = "Scientific measurements";
    wrap.appendChild(header);

    var subheader = document.createElement("div");
    subheader.className = "ms-explain-subheader";
    subheader.textContent =
      "Every number Cortex tracks about this memory, with plain-language explanations.";
    wrap.appendChild(subheader);

    // Include `stage` as an explicit item (not in FIELDS).
    var entries = [];
    if (mem.stage || mem.consolidation_stage || mem.consolidationStage) {
      entries.push({
        snake: "stage",
        label: FRIENDLY_LABEL.stage,
        explain: EXPLAIN.stage,
        kind: "text",
        value: mem.stage || mem.consolidation_stage || mem.consolidationStage,
      });
    }
    for (var i = 0; i < FIELDS.length; i++) {
      var f = FIELDS[i];
      var v = pick(mem, f.keys);
      if (v === undefined || v === null || v === "") continue;
      if (f.kind === "flag" && !v) continue;
      // Don't bother showing zero-value counters.
      if (f.kind === "count" && Number(v) === 0) continue;
      var snake = f.keys[0];
      entries.push({
        snake: snake,
        label: FRIENDLY_LABEL[snake] || f.label,
        explain: EXPLAIN[snake] || "",
        kind: f.kind,
        range: f.range,
        unit: f.unit,
        value: v,
      });
    }

    var list = document.createElement("div");
    list.className = "ms-explain-list";

    entries.forEach(function (e) {
      var row = document.createElement("div");
      row.className = "ms-explain-row";

      var head = document.createElement("div");
      head.className = "ms-explain-row-head";

      var label = document.createElement("span");
      label.className = "ms-explain-label";
      label.textContent = e.label;
      head.appendChild(label);

      var valEl = document.createElement("span");
      valEl.className = "ms-explain-value";
      valEl.appendChild(buildValueRepresentation(e));
      head.appendChild(valEl);

      row.appendChild(head);

      if (e.explain) {
        var note = document.createElement("div");
        note.className = "ms-explain-note";
        note.textContent = e.explain;
        row.appendChild(note);
      }
      list.appendChild(row);
    });

    wrap.appendChild(list);
    return wrap;
  }

  function buildValueRepresentation(e) {
    var frag = document.createElement("span");
    frag.className = "ms-explain-value-inner";
    var v = e.value;
    if (e.kind === "bar") {
      var lo = (e.range || [0, 1])[0], hi = (e.range || [0, 1])[1];
      var n = Number(v);
      var pct = hi === lo ? 0 : clamp01((n - lo) / (hi - lo));
      var bar = document.createElement("span");
      bar.className = "ms-bar ms-explain-bar";
      var fill = document.createElement("span");
      fill.className = "ms-bar-fill";
      fill.style.width = (pct * 100).toFixed(0) + "%";
      bar.appendChild(fill);
      frag.appendChild(bar);
      var num = document.createElement("span");
      num.className = "ms-v ms-v-num";
      num.textContent = fmtNum(n);
      frag.appendChild(num);
    } else if (e.kind === "bipolar") {
      var lo2 = (e.range || [-1, 1])[0], hi2 = (e.range || [-1, 1])[1];
      var n2 = Number(v);
      var pct2 = clamp01((n2 - lo2) / (hi2 - lo2));
      var bar2 = document.createElement("span");
      bar2.className = "ms-bar ms-bar-bipolar ms-explain-bar";
      var marker = document.createElement("span");
      marker.className = "ms-bar-marker";
      marker.style.left = (pct2 * 100).toFixed(0) + "%";
      bar2.appendChild(marker);
      frag.appendChild(bar2);
      var num2 = document.createElement("span");
      num2.className = "ms-v ms-v-num";
      num2.textContent = (n2 > 0 ? "+" : "") + fmtNum(n2);
      frag.appendChild(num2);
    } else if (e.kind === "count") {
      var count = document.createElement("span");
      count.className = "ms-v ms-v-count";
      count.textContent = fmtNum(Number(v)) + (e.unit || "");
      frag.appendChild(count);
    } else if (e.kind === "flag") {
      var flag = document.createElement("span");
      flag.className = "ms-v ms-v-flag";
      flag.textContent = "Yes";
      frag.appendChild(flag);
    } else if (e.kind === "age") {
      var age = fmtAge(v);
      var at = document.createElement("span");
      at.className = "ms-v ms-v-age";
      at.textContent = age ? age + " ago" : String(v);
      frag.appendChild(at);
    } else {
      var t = document.createElement("span");
      t.className = "ms-v ms-v-text";
      t.textContent = String(v);
      frag.appendChild(t);
    }
    return frag;
  }

  JUG._memSci = {
    buildSciencePanel: buildSciencePanel,
    buildEmotionChip: buildEmotionChip,
    buildMeaningSection: buildMeaningSection,
    buildExplainedPanel: buildExplainedPanel,
    FIELDS: FIELDS,
    EMOTION_COLORS: EMOTION_COLORS,
    EXPLAIN: EXPLAIN,
    FRIENDLY_LABEL: FRIENDLY_LABEL,
  };
})();
