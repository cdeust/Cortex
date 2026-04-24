// Cortex — Workflow Graph: rich side panel per kind.
// Renders metadata for every node kind, and wires:
//   * file  → "See diff" button → JUG._diff.show(path) (opens #diff-modal)
//   * discussion → "View conversation" button → JUG._disc.openConversationModal(sessionId)
//   * memory → full body preview + tags + stage/heat
//   * skill/hook/command/agent → details specific to the kind
//   * domain/tool_hub → aggregate stats from the graph context
// Exposes JUG._wfg.buildSidePanel(container) -> { root, show(n, ctx), hide() }.
(function () {
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }

  function row(key, val) {
    var r = el('div', 'wfg-panel__row');
    var k = el('div', 'wfg-panel__key'); k.textContent = key;
    var v = el('div', 'wfg-panel__val'); v.textContent = val == null ? '—' : String(val);
    r.appendChild(k); r.appendChild(v);
    return r;
  }

  function humanDate(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      var now = Date.now();
      var diff = Math.floor((now - d.getTime()) / 1000);
      if (diff < 60) return 'just now';
      if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
      if (diff < 86400) return Math.floor(diff / 3600) + ' h ago';
      if (diff < 604800) return Math.floor(diff / 86400) + ' d ago';
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { return String(iso); }
  }

  function humanDuration(ms) {
    var v = Number(ms);
    if (!v || isNaN(v)) return '—';
    if (v < 60000) return Math.round(v / 1000) + ' s';
    if (v < 3600000) return Math.round(v / 60000) + ' min';
    var h = Math.floor(v / 3600000);
    var m = Math.round((v % 3600000) / 60000);
    return h + ' h ' + m + ' min';
  }

  function section(title) {
    var s = el('div', 'wfg-panel__section');
    var h = el('div', 'wfg-panel__section-title'); h.textContent = title;
    s.appendChild(h);
    return s;
  }

  function preview(text, max) {
    var pre = el('pre', 'wfg-panel__preview');
    var t = String(text || '');
    pre.textContent = t.length > max ? t.slice(0, max) + '…' : t;
    return pre;
  }

  function tagChip(tag) {
    var c = el('span', 'wfg-panel__chip');
    c.textContent = tag;
    return c;
  }

  // ── Plain-language helpers (delegated to workflow_graph_humanize.js) ─

  function hum() {
    return (window.JUG && window.JUG._wfgHumanize) || {};
  }

  // One-line plain-English description at the top of the panel.
  function renderPlainDescription(body, n, ctx) {
    var h = hum();
    if (!h.plainDescription) return;
    var text = h.plainDescription(n, ctx);
    if (!text) return;
    var p = el('p', 'wfg-panel__plain');
    p.textContent = text;
    body.appendChild(p);
  }

  // Visual heat badge: "Hot" / "Warm" / "Cool" / "Cold" + colored bar.
  // Non-tech users see "Hot 78%"; the raw 0.78 stays in Technical details.
  function heatRow(value) {
    var h = hum();
    if (!h.heatBadge) return row('Priority', value);
    var b = h.heatBadge(value);
    if (!b) return row('Priority', '—');
    var r = el('div', 'wfg-panel__row');
    // Eco audit: the value is retrieval PRIORITY, not CPU activity.
    // "Activity" invited "CPU %" misreading.
    var k = el('div', 'wfg-panel__key'); k.textContent = 'Priority';
    var v = el('div', 'wfg-panel__val');
    var badge = el('span', 'wfg-panel__badge');
    badge.textContent = b.label + ' · ' + b.pct + '%';
    badge.style.background = b.color + '22';
    badge.style.borderColor = b.color + '60';
    badge.style.color = b.color;
    v.appendChild(badge);
    r.appendChild(k); r.appendChild(v);
    return r;
  }

  // Memory stage with plain-language label + hint.
  function stageRows(stage) {
    var h = hum();
    var out = [];
    if (!stage) return out;
    var label = h.stageLabel ? h.stageLabel(stage) : stage;
    out.push(row('Status', label));
    if (h.stageHint) {
      var hint = h.stageHint(stage);
      if (hint) {
        var r = el('div', 'wfg-panel__hint');
        r.textContent = hint;
        out.push(r);
      }
    }
    return out;
  }

  // Collapsible "Technical details" section holding every raw field the
  // backend surfaced. Hidden by default; one click reveals it. Users who
  // want to debug, copy IDs, or check the raw heat float get it one tap
  // away; everyone else never sees the jargon.
  function renderTechnicalDetails(body, n) {
    var h = hum();
    var pretty = h.prettyFieldKey || function (k) { return k; };
    // Pick field set: everything except what we've already shown
    // humanized, and except fields that are structural (body, tags).
    var SKIP = {
      id: 1, kind: 1, label: 1, color: 1, size: 1,
      body: 1, tags: 1, is_protected: 1, is_stale: 1,
    };
    var keys = Object.keys(n).filter(function (k) {
      if (SKIP[k]) return false;
      var v = n[k];
      if (v == null) return false;
      if (Array.isArray(v) && v.length === 0) return false;
      if (typeof v === 'object' && Object.keys(v).length === 0) return false;
      return true;
    });
    if (!keys.length) return;
    // Collapsible <details> — native HTML, no JS needed.
    var d = document.createElement('details');
    d.className = 'wfg-panel__advanced';
    var sum = document.createElement('summary');
    sum.textContent = 'Technical details';
    d.appendChild(sum);
    var wrap = el('div', 'wfg-panel__advanced-body');
    // Vygotsky ZPD bridge: show both the plain label AND the raw key
    // so a growing reader can build the mapping (e.g.
    // "Priority (raw) · heat_base"). Raw key rendered dim/mono so
    // the plain label remains the primary anchor.
    keys.sort().forEach(function (k) {
      var v = n[k];
      if (typeof v === 'object') v = JSON.stringify(v);
      if (typeof v === 'number' && !Number.isInteger(v)) v = v.toFixed(4);
      var r = el('div', 'wfg-panel__row');
      var keyCell = el('div', 'wfg-panel__key');
      keyCell.textContent = pretty(k);
      // Only attach the raw-key bridge when pretty(k) is actually
      // a translation (not when it falls through to the titleizer).
      if (pretty(k) !== k && pretty(k).toLowerCase() !== k.replace(/_/g, ' ')) {
        var raw = el('span', 'wfg-panel__raw-key');
        raw.textContent = ' · ' + k;
        keyCell.appendChild(raw);
      }
      var valCell = el('div', 'wfg-panel__val');
      valCell.textContent = v == null ? '—' : String(v);
      r.appendChild(keyCell); r.appendChild(valCell);
      wrap.appendChild(r);
    });
    d.appendChild(wrap);
    body.appendChild(d);
  }

  function actionBtn(label, onClick) {
    var b = el('button', 'wfg-panel__action');
    b.type = 'button'; b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  function domainLabel(ctx, domain_id) {
    var d = ctx.byId[domain_id];
    return d ? (d.label || d.id.replace('domain:', '')) : (domain_id || '—');
  }

  function countNeighborsByKind(n, ctx) {
    var out = {};
    var adj = ctx.adj[n.id] || {};
    for (var id in adj) {
      var kind = (ctx.byId[id] && ctx.byId[id].kind) || '?';
      out[kind] = (out[kind] || 0) + 1;
    }
    return out;
  }

  // Gather neighbors split by (edge-kind, direction, neighbor-kind) so
  // we can show contextual lists like "Called from", "Uses", etc.
  function collectNeighbors(n, ctx, filter) {
    // filter(edge, isOutgoing, neighborNode) -> boolean (include?)
    var out = [];
    var seen = {};
    for (var i = 0; i < ctx.edges.length; i++) {
      var e = ctx.edges[i];
      var sId = e.source.id || e.source;
      var tId = e.target.id || e.target;
      var isOut = sId === n.id;
      var isIn  = tId === n.id;
      if (!isOut && !isIn) continue;
      var other = isOut ? ctx.byId[tId] : ctx.byId[sId];
      if (!other) continue;
      if (!filter(e, isOut, other)) continue;
      if (seen[other.id]) continue;
      seen[other.id] = 1;
      out.push(other);
    }
    return out;
  }

  // Render a list of named neighbor nodes under a section title.
  // Truncates to MAX; shows "+N more" footer if exceeded.
  var NEIGHBOR_MAX = 24;
  function renderNeighborList(body, sectionTitle, neighbors, ctx, onClickFactory) {
    if (!neighbors || !neighbors.length) return;
    var s = section(sectionTitle + ' (' + neighbors.length + ')');
    var shown = neighbors.slice(0, NEIGHBOR_MAX);
    shown.forEach(function (nb) {
      var r = el('div', 'wfg-panel__row wfg-panel__row--clickable');
      var k = el('div', 'wfg-panel__key');
      // Vygotsky audit: this bypassed the humanizer and showed the raw
      // kind string ("symbol", "tool_hub") on every neighbor row. Go
      // through kindLabel for consistent lay-vocabulary.
      var h = (window.JUG && window.JUG._wfgHumanize) || {};
      k.textContent = (h.kindLabel ? h.kindLabel(nb.kind) : (nb.kind || '?'));
      var v = el('div', 'wfg-panel__val');
      var a = el('a', 'wfg-panel__link');
      a.textContent = nb.label || nb.path || nb.id;
      a.href = '#';
      a.title = nb.path || nb.id;
      var onClick = onClickFactory ? onClickFactory(nb) : function (ev) {
        ev.preventDefault();
        if (window.JUG && JUG.wfgApplyFilter) {
          // Focus this node in the graph by dispatching a selection.
          if (typeof JUG.emit === 'function') JUG.emit('graph:selectNode', nb);
        }
      };
      a.addEventListener('click', onClick);
      v.appendChild(a);
      r.appendChild(k); r.appendChild(v);
      s.appendChild(r);
    });
    if (neighbors.length > NEIGHBOR_MAX) {
      var more = el('div', 'wfg-panel__more');
      more.textContent = '+' + (neighbors.length - NEIGHBOR_MAX) + ' more…';
      s.appendChild(more);
    }
    body.appendChild(s);
  }

  function renderCommon(body, n, ctx) {
    // Vygotsky audit: "Domain" is internal vocabulary; KIND_LABELS
    // translates the node kind to "Project". Use the same word here
    // for consistency across the panel.
    if (n.domain_id) body.appendChild(row('Project', domainLabel(ctx, n.domain_id)));
    if (ctx.degree[n.id] != null) body.appendChild(row('Connections', ctx.degree[n.id]));
  }

  function renderDomain(body, n, ctx) {
    renderCommon(body, n, ctx);
    var kinds = countNeighborsByKind(n, ctx);
    var s = section('Cloud contents');
    var order = ['tool_hub', 'file', 'skill', 'hook', 'agent', 'command', 'memory', 'discussion'];
    for (var i = 0; i < order.length; i++) {
      if (kinds[order[i]]) s.appendChild(row(order[i], kinds[order[i]]));
    }
    body.appendChild(s);
  }

  function renderToolHub(body, n, ctx) {
    body.appendChild(row('Tool', n.tool || n.label));
    renderCommon(body, n, ctx);
    var weight = 0;
    var files = collectNeighbors(n, ctx, function (e, isOut, other) {
      if (e.kind !== 'tool_used_file') return false;
      if (other.kind !== 'file') return false;
      weight += (e.weight || 1);
      return true;
    });
    body.appendChild(row('Files touched', files.length));
    body.appendChild(row('Total uses', Math.round(weight)));
    renderNeighborList(body, 'Files accessed by this tool', files, ctx);
    var cmds = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_in_hub' && other.kind === 'command';
    });
    renderNeighborList(body, 'Commands in this hub', cmds, ctx);
  }

  function renderFile(body, n, ctx) {
    if (n.path) body.appendChild(row('Path', n.path));
    if (n.primary_cluster) {
      var h = hum();
      var c = (h.primaryClusterLabel && h.primaryClusterLabel(n.primary_cluster))
        || n.primary_cluster;
      body.appendChild(row('How it was used', c));
    }
    if (n.first_seen) body.appendChild(row('First seen', humanDate(n.first_seen)));
    if (n.last_accessed) body.appendChild(row('Last access', humanDate(n.last_accessed)));
    if (n.last_modified) body.appendChild(row('Last modified', humanDate(n.last_modified)));
    renderCommon(body, n, ctx);
    if (n.extra_domain_ids && n.extra_domain_ids.length) {
      var s = section('Also in domains');
      n.extra_domain_ids.forEach(function (d) {
        s.appendChild(row('', domainLabel(ctx, d)));
      });
      body.appendChild(s);
    }
    // Tools that touched this file, by name.
    var tools = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'tool_used_file' && other.kind === 'tool_hub';
    });
    renderNeighborList(body, 'Accessed by tools', tools, ctx);
    // Symbols defined in this file.
    var defined = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'defined_in' && other.kind === 'symbol';
    });
    renderNeighborList(body, 'Symbols defined here', defined, ctx);
    // Discussions / commands that touched the file.
    var discs = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_touched_file' && other.kind === 'discussion';
    });
    renderNeighborList(body, 'Discussions involving this file', discs, ctx);
    var cmds = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_touched_file' && other.kind === 'command';
    });
    renderNeighborList(body, 'Commands that touched this file', cmds, ctx);
    // Cross-file imports landing here.
    var imps = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'imports';
    });
    renderNeighborList(body, 'Imports / imported by', imps, ctx);
    // Edit/Write files → diff button; read-only files → no diff.
    if (n.primary_cluster === 'edit_write' && n.path) {
      var ds = section('Diff');
      ds.appendChild(actionBtn('See diff against HEAD', function () {
        if (window.JUG && JUG._diff && typeof JUG._diff.show === 'function') {
          JUG._diff.show(n.path, false);
        } else {
          console.warn('[wfg] diff modal unavailable');
        }
      }));
      body.appendChild(ds);
    }
  }

  function renderMemory(body, n, ctx) {
    // Plain-language stage ("Just learned" instead of "LABILE") + hint.
    stageRows(n.stage).forEach(function (r) { body.appendChild(r); });
    // Visual heat badge (Hot/Warm/Cool/Cold) — raw 0.xxx is in Technical.
    if (n.heat != null) body.appendChild(heatRow(n.heat));
    if (n.created_at) body.appendChild(row('Created', humanDate(n.created_at)));
    renderCommon(body, n, ctx);
    if (n.tags && n.tags.length) {
      var tagWrap = section('Tags');
      var chips = el('div', 'wfg-panel__chips');
      n.tags.forEach(function (t) { chips.appendChild(tagChip(t)); });
      tagWrap.appendChild(chips);
      body.appendChild(tagWrap);
    }
    if (n.body) {
      var bs = section('What was remembered');
      bs.appendChild(preview(n.body, 4000));
      body.appendChild(bs);
    }
  }

  function renderDiscussion(body, n, ctx) {
    if (n.session_id) body.appendChild(row('Session', n.session_id));
    if (n.count != null) body.appendChild(row('Messages', n.count));
    if (n.started_at) body.appendChild(row('Started', humanDate(n.started_at)));
    if (n.last_activity) body.appendChild(row('Last activity', humanDate(n.last_activity)));
    if (n.duration_ms != null)
      body.appendChild(row('Duration', humanDuration(n.duration_ms)));
    renderCommon(body, n, ctx);
    var touched = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_touched_file' && other.kind === 'file';
    });
    renderNeighborList(body, 'Files touched in session', touched, ctx);
    var usedTools = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_used_tool' && other.kind === 'tool_hub';
    });
    renderNeighborList(body, 'Tools used', usedTools, ctx);
    var ranCmds = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_ran_command' && other.kind === 'command';
    });
    renderNeighborList(body, 'Commands run', ranCmds, ctx);
    var spawnedAgents = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_spawned_agent' && other.kind === 'agent';
    });
    renderNeighborList(body, 'Agents spawned', spawnedAgents, ctx);
    if (n.session_id) {
      var ds = section('Conversation');
      ds.appendChild(actionBtn('View full conversation', function () {
        if (window.JUG && JUG._disc && typeof JUG._disc.openConversationModal === 'function') {
          JUG._disc.openConversationModal(n.session_id);
        } else {
          console.warn('[wfg] conversation modal unavailable');
        }
      }));
      body.appendChild(ds);
    }
  }

  function renderSkill(body, n, ctx) {
    if (n.path) body.appendChild(row('File', n.path));
    renderCommon(body, n, ctx);
    if (n.body) {
      var bs = section('Definition');
      bs.appendChild(preview(n.body, 2000));
      body.appendChild(bs);
    }
  }

  function renderHook(body, n, ctx) {
    if (n.event) body.appendChild(row('Event', n.event));
    if (n.path) body.appendChild(row('Command', n.path));
    renderCommon(body, n, ctx);
  }

  function renderCommand(body, n, ctx) {
    if (n.count != null) body.appendChild(row('Invocations', n.count));
    if (n.first_seen) body.appendChild(row('First seen', humanDate(n.first_seen)));
    if (n.last_accessed) body.appendChild(row('Last invoked', humanDate(n.last_accessed)));
    renderCommon(body, n, ctx);
    if (n.body) {
      var bs = section('Command line');
      bs.appendChild(preview(n.body, 1000));
      body.appendChild(bs);
    }
    var touched = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_touched_file' && other.kind === 'file';
    });
    renderNeighborList(body, 'Files this command touched', touched, ctx);
    var parentHub = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_in_hub' && other.kind === 'tool_hub';
    });
    renderNeighborList(body, 'Part of tool hub', parentHub, ctx);
  }

  function renderAgent(body, n, ctx) {
    if (n.subagent_type) body.appendChild(row('Agent type', n.subagent_type));
    if (n.count != null) body.appendChild(row('Invocations', n.count));
    renderCommon(body, n, ctx);
  }

  function renderSymbol(body, n, ctx) {
    // Identity — use plain-language type labels.
    var h = hum();
    if (n.symbol_type) {
      var t = (h.symbolTypeLabel && h.symbolTypeLabel(n.symbol_type)) || n.symbol_type;
      body.appendChild(row('Type', t));
    }
    if (n.path) body.appendChild(row('File', n.path));
    if (n.label) body.appendChild(row('Name', n.label));
    renderCommon(body, n, ctx);

    // Parent file (defined_in → file).
    var parents = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'defined_in' && other.kind === 'file' && isOut;
    });
    renderNeighborList(body, 'Defined in file', parents, ctx);

    // Class / module membership (member_of → class/module symbol).
    var containers = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'member_of' && other.kind === 'symbol' && isOut;
    });
    renderNeighborList(body, 'Member of', containers, ctx);

    // Methods of this class/module (member_of ← other symbols).
    var members = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'member_of' && other.kind === 'symbol' && !isOut;
    });
    renderNeighborList(body, 'Methods / members', members, ctx);

    // Calls: outgoing = "Calls these", incoming = "Called from".
    var callsOut = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'calls' && isOut;
    });
    renderNeighborList(body, 'Calls these symbols', callsOut, ctx);
    var callsIn = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'calls' && !isOut;
    });
    renderNeighborList(body, 'Called from', callsIn, ctx);

    // Imports landing on this symbol (file → imports → symbol).
    var importedBy = collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'imports' && other.kind === 'file' && !isOut;
    });
    renderNeighborList(body, 'Imported by files', importedBy, ctx);
  }

  var RENDERERS = {
    domain: renderDomain,
    tool_hub: renderToolHub,
    file: renderFile,
    memory: renderMemory,
    discussion: renderDiscussion,
    skill: renderSkill,
    hook: renderHook,
    command: renderCommand,
    agent: renderAgent,
    symbol: renderSymbol,
  };

  function buildSidePanel(container) {
    var wfg = window.JUG._wfg;
    var root = el('aside', 'wfg-panel');
    root.setAttribute('aria-hidden', 'true');
    var close = el('button', 'wfg-panel__close');
    close.type = 'button'; close.setAttribute('aria-label', 'Close');
    close.textContent = '×';
    var kind  = el('div', 'wfg-panel__kind');
    var title = el('div', 'wfg-panel__title');
    var body  = el('div', 'wfg-panel__body');
    root.appendChild(close); root.appendChild(kind);
    root.appendChild(title); root.appendChild(body);
    container.appendChild(root);

    close.addEventListener('click', hide);

    function show(n, ctx) {
      root.classList.add('wfg-panel--open');
      root.setAttribute('aria-hidden', 'false');
      // Humanized kind label ("Memory" not "memory", "Code item" not
      // "symbol") — falls back to raw kind when humanizer absent.
      var h = (window.JUG && window.JUG._wfgHumanize) || {};
      kind.textContent = (h.kindLabel ? h.kindLabel(n.kind) : n.kind) || '—';
      title.textContent = wfg.labelOf(n);
      body.innerHTML = '';
      // Plain-language one-sentence description at the very top, before
      // any field table. This is the non-tech reader's entry point.
      renderPlainDescription(body, n, ctx);
      var fn = RENDERERS[n.kind];
      if (fn) fn(body, n, ctx);
      else {
        // Unknown kind — fall back to raw JSON dump (never fail silently).
        var pre = el('pre', 'wfg-panel__preview');
        try { pre.textContent = JSON.stringify(n, null, 2).slice(0, 2000); }
        catch (_) { pre.textContent = String(n); }
        body.appendChild(pre);
      }
      // Collapsible "Technical details" footer — every raw field the
      // backend emitted, one click away. Hidden by default so non-tech
      // users never confront the jargon.
      renderTechnicalDetails(body, n);
    }

    function hide() {
      root.classList.remove('wfg-panel--open');
      root.setAttribute('aria-hidden', 'true');
    }

    return { root: root, show: show, hide: hide };
  }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.buildSidePanel = buildSidePanel;
})();
