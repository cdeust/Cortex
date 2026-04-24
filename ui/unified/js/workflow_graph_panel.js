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
  function renderPlainDescription(body, n) {
    var h = hum();
    if (!h.plainDescription) return;
    var text = h.plainDescription(n);
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

  // renderTechnicalDetails + actionBtn live in
  // workflow_graph_panel_helpers.js — proxied here so the rest of the
  // file keeps its local names.
  function renderTechnicalDetails(body, n) {
    return _neighbors().renderTechnicalDetails(body, n, hum());
  }
  function actionBtn(label, onClick) {
    return _neighbors().actionBtn(label, onClick);
  }

  // Neighbor traversal + rendering lives in
  // workflow_graph_panel_helpers.js (Dijkstra §4.1 split 2026-04-24).
  // We proxy here so callers inside this file keep working.
  function _neighbors() {
    return (window.JUG && window.JUG._wfgPanelNeighbors) || {};
  }
  function domainLabel(ctx, domain_id) {
    return _neighbors().domainLabel(ctx, domain_id);
  }
  function countNeighborsByKind(n, ctx) {
    return _neighbors().countNeighborsByKind(n, ctx);
  }
  function collectNeighbors(n, ctx, filter) {
    return _neighbors().collectNeighbors(n, ctx, filter);
  }
  function renderNeighborList(body, title, neighbors, ctx, onClickFactory) {
    return _neighbors().renderNeighborList(body, title, neighbors, ctx, onClickFactory);
  }

  function renderCommon(body, n, ctx) {
    // Vygotsky audit: "Domain" is internal vocabulary; KIND_LABELS
    // translates the node kind to "Project". Use the same word here
    // for consistency across the panel.
    if (n.domain_id) body.appendChild(row('Project', domainLabel(ctx, n.domain_id)));
    if (ctx.degree[n.id] != null) body.appendChild(row('Connections', ctx.degree[n.id]));
  }

  // Per-kind render<Kind> functions + the dispatch table live in
  // workflow_graph_panel_renderers.js (Dijkstra §4.1 split, 2026-04-24).
  // Publish the primitives renderers consume so they can access them
  // without reaching into private panel state.
  window.JUG = window.JUG || {};
  window.JUG._wfgPanelHelpers = {
    el: el,
    row: row,
    section: section,
    preview: preview,
    tagChip: tagChip,
    actionBtn: actionBtn,
    humanDate: humanDate,
    humanDuration: humanDuration,
    domainLabel: domainLabel,
    collectNeighbors: collectNeighbors,
    renderNeighborList: renderNeighborList,
    countNeighborsByKind: countNeighborsByKind,
    renderCommon: renderCommon,
    heatRow: heatRow,
    stageRows: stageRows,
  };


  function rendererFor(kind) {
    var r = (window.JUG && window.JUG._wfgRenderers);
    return r && typeof r.get === 'function' ? r.get(kind) : null;
  }

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
      renderPlainDescription(body, n);
      var fn = rendererFor(n.kind);
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
