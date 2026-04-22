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

  function renderCommon(body, n, ctx) {
    if (n.domain_id) body.appendChild(row('Domain', domainLabel(ctx, n.domain_id)));
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
    var files = 0, weight = 0;
    for (var i = 0; i < ctx.edges.length; i++) {
      var e = ctx.edges[i];
      if (e.kind !== 'tool_used_file') continue;
      if (e.source.id !== n.id && e.target.id !== n.id) continue;
      files += 1;
      weight += (e.weight || 1);
    }
    body.appendChild(row('Files touched', files));
    body.appendChild(row('Total uses', Math.round(weight)));
  }

  function renderFile(body, n, ctx) {
    if (n.path) body.appendChild(row('Path', n.path));
    if (n.primary_cluster) body.appendChild(row('Primary tool', n.primary_cluster));
    renderCommon(body, n, ctx);
    if (n.extra_domain_ids && n.extra_domain_ids.length) {
      var s = section('Also in domains');
      n.extra_domain_ids.forEach(function (d) {
        s.appendChild(row('', domainLabel(ctx, d)));
      });
      body.appendChild(s);
    }
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
    if (n.stage) body.appendChild(row('Stage', n.stage));
    if (n.heat != null) body.appendChild(row('Heat', (+n.heat).toFixed(3)));
    if (n.created_at) body.appendChild(row('Created', n.created_at));
    renderCommon(body, n, ctx);
    if (n.tags && n.tags.length) {
      var tagWrap = section('Tags');
      var chips = el('div', 'wfg-panel__chips');
      n.tags.forEach(function (t) { chips.appendChild(tagChip(t)); });
      tagWrap.appendChild(chips);
      body.appendChild(tagWrap);
    }
    if (n.body) {
      var bs = section('Content');
      bs.appendChild(preview(n.body, 4000));
      body.appendChild(bs);
    }
  }

  function renderDiscussion(body, n, ctx) {
    if (n.session_id) body.appendChild(row('Session', n.session_id));
    if (n.count != null) body.appendChild(row('Messages', n.count));
    renderCommon(body, n, ctx);
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
    renderCommon(body, n, ctx);
    if (n.body) {
      var bs = section('Command line');
      bs.appendChild(preview(n.body, 1000));
      body.appendChild(bs);
    }
  }

  function renderAgent(body, n, ctx) {
    if (n.subagent_type) body.appendChild(row('Agent type', n.subagent_type));
    if (n.count != null) body.appendChild(row('Invocations', n.count));
    renderCommon(body, n, ctx);
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
      kind.textContent = n.kind || '—';
      title.textContent = wfg.labelOf(n);
      body.innerHTML = '';
      var fn = RENDERERS[n.kind];
      if (fn) fn(body, n, ctx);
      else {
        // Unknown kind — fall back to raw JSON dump (never fail silently).
        var pre = el('pre', 'wfg-panel__preview');
        try { pre.textContent = JSON.stringify(n, null, 2).slice(0, 2000); }
        catch (_) { pre.textContent = String(n); }
        body.appendChild(pre);
      }
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
