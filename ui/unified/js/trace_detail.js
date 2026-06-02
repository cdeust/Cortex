// Cortex — Trace detail-panel content (single panel, expandable sections).
//
// Renders trace nodes (domain/session/action/prompt/file) INTO the one
// #detail-content panel that detail_panel.js owns. Sections use native
// <details>/<summary> and lazy-fetch their data on first expand:
//   file    → Git diff, AST symbols, Impact (opens the flow diagram)
//   session → Conversation transcript, overview
//   action  → tool input + causal (its files / prompt)
//   prompt  → full text
// Exposed as JUG._traceDetail.{build, wire}.
(function () {
  'use strict';

  var TOOL_DOT = {
    Read: '#38BDF8', NotebookRead: '#38BDF8', Grep: '#7DD3FC', Glob: '#7DD3FC',
    Edit: '#FBBF24', MultiEdit: '#FBBF24', NotebookEdit: '#FBBF24',
    Write: '#34D399', Bash: '#F87171', Task: '#EC4899', Agent: '#EC4899',
    WebFetch: '#A78BFA', WebSearch: '#A78BFA',
  };
  var KIND_COLOR = {
    domain: '#FCD34D', session: '#FCD34D', prompt: '#22D3EE',
    action: '#94A3B8', file: '#06B6D4',
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function shortStr(t, n) {
    n = n || 60;
    var s = String(t == null ? '' : t).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }
  function color(node) {
    var k = node.kind || node.type;
    if (k === 'action' && node.tool && TOOL_DOT[node.tool]) return TOOL_DOT[node.tool];
    return KIND_COLOR[k] || '#00d2ff';
  }
  function kindLabel(node) {
    var k = node.kind || node.type;
    if (k === 'action') return node.tool || 'action';
    return k;
  }
  function header(node) {
    var c = color(node);
    return '<div class="node-badge" style="background:' + c + '14;border-color:'
      + c + '40;color:' + c + '">'
      + '<span style="width:5px;height:5px;border-radius:50%;background:' + c
      + ';display:inline-block"></span> ' + esc(kindLabel(node)) + '</div>'
      + '<h2>' + esc(node.label || node.id || '') + '</h2>';
  }
  // A collapsible section. ``open`` expands by default; ``lazy`` marks it
  // for wire() to fetch its body on first expand.
  function section(title, id, bodyHtml, opts) {
    opts = opts || {};
    return '<details class="td-sec"' + (opts.open ? ' open' : '')
      + (opts.lazy ? ' data-lazy="' + opts.lazy + '"' : '')
      + (opts.path ? ' data-path="' + esc(opts.path) + '"' : '')
      + (opts.sid ? ' data-sid="' + esc(opts.sid) + '"' : '') + '>'
      + '<summary>' + esc(title) + '</summary>'
      + '<div class="td-sec-body" id="' + id + '">' + (bodyHtml || '') + '</div>'
      + '</details>';
  }

  // ── build(node) → HTML for #detail-content ──
  function build(node) {
    var k = node.kind || node.type;
    var h = header(node);
    if (k === 'domain') {
      h += '<div class="conn-item">' + (node.session_count || '?')
        + ' sessions · click the hub to expand them on the graph</div>';
      return h;
    }
    if (k === 'prompt') {
      h += section('User message', 'td-prompt',
        '<div class="detail-text">' + esc(node.full || node.label || '') + '</div>',
        { open: true });
      if (node.ts) h += '<div class="conn-item" style="color:var(--text-dim)">' + esc(node.ts) + '</div>';
      return h;
    }
    if (k === 'action') {
      var tool = node.tool || 'action';
      h += '<div class="conn-item">Tool: ' + esc(tool) + '</div>'
        + (node.ts ? '<div class="conn-item" style="color:var(--text-dim)">' + esc(node.ts) + '</div>' : '');
      h += section('Causal context', 'td-action-causal',
        '<div class="conn-item" style="color:var(--text-dim)">Part of session '
        + esc((node.session_id || '').slice(0, 8))
        + '. Expand the session on the graph to see the full chain.</div>',
        { open: true });
      return h;
    }
    if (k === 'session') {
      var sid = node.session_id || String(node.id).replace(/^session:/, '');
      h += '<div class="conn-item">Actions: ' + (node.action_count != null ? node.action_count : '?') + '</div>'
        + (node.git_branch ? '<div class="conn-item">Branch: ' + esc(node.git_branch) + '</div>' : '')
        + (node.started_at ? '<div class="conn-item" style="color:var(--text-dim)">Started ' + esc(node.started_at) + '</div>' : '');
      h += section('Conversation', 'td-convo', 'loading transcript…',
        { open: true, lazy: 'convo', sid: sid });
      return h;
    }
    if (k === 'file') {
      var path = node.path || String(node.id).replace(/^file:/, '');
      h += '<div class="conn-item" style="color:var(--text-dim)">' + esc(path) + '</div>';
      h += section('Git diff', 'td-git', 'loading diff…', { open: true, lazy: 'file', path: path });
      h += section('AST symbols', 'td-ast', '', { lazy: 'file', path: path });
      h += section('Impact / dependencies', 'td-impact',
        '<div class="conn-item" style="color:var(--text-dim)">Open the impact diagram →</div>',
        { path: path });
      return h;
    }
    return h;
  }

  // ── wire(content, node) → lazy fetch on expand + impact button ──
  function wire(content, node) {
    var lazyDone = {};
    content.querySelectorAll('details[data-lazy]').forEach(function (det) {
      var run = function () {
        var key = det.querySelector('.td-sec-body').id;
        if (lazyDone[key]) return; lazyDone[key] = true;
        var kind = det.getAttribute('data-lazy');
        if (kind === 'convo') _loadConvo(det.getAttribute('data-sid'));
        else if (kind === 'file') _loadFile(det.getAttribute('data-path'), content);
      };
      if (det.open) run();
      det.addEventListener('toggle', function () { if (det.open) run(); });
    });
    // Impact section: open the dependency diagram in the flow panel.
    var impact = content.querySelector('#td-impact');
    if (impact) {
      var path = node.path || String(node.id || '').replace(/^file:/, '');
      impact.addEventListener('click', function () {
        if (window.TraceView && TraceView.showImpact) TraceView.showImpact(path);
      });
      impact.style.cursor = 'pointer';
    }
  }

  function _fetch(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  function _loadConvo(sid) {
    var slot = document.getElementById('td-convo');
    if (!slot || !sid) return;
    _fetch('/api/discussion/' + encodeURIComponent(sid))
      .then(function (d) {
        var all = (d && (d.messages || d.turns)) || [];
        var msgs = all.filter(function (m) {
          return String(m.text || m.content || '').trim().length > 0;
        });
        if (!msgs.length) { slot.textContent = 'No transcript text.'; return; }
        slot.innerHTML = msgs.slice(0, 14).map(function (m) {
          return '<div class="td-msg"><span class="td-role">' + esc(m.role || m.type || '')
            + '</span> ' + esc(shortStr(m.text || m.content || '', 200)) + '</div>';
        }).join('') + (msgs.length > 14 ? '<div class="conn-item">… ' + (msgs.length - 14) + ' more</div>' : '');
      })
      .catch(function () { slot.textContent = 'Transcript unavailable.'; });
  }

  function _diffHtml(git) {
    if (!git || !git.available) return '<div class="conn-item" style="color:var(--text-dim)">no git data</div>';
    var lines = git.lines || [];
    if (!lines.length) return '<div class="conn-item" style="color:var(--text-dim)">' + esc(git.diff_type || 'no changes') + '</div>';
    var h = '<div class="conn-item" style="color:var(--text-dim)">' + esc(git.diff_type || '') + '</div><div class="td-diff">';
    lines.slice(0, 300).forEach(function (ln) {
      h += '<div class="td-diff-' + (ln.type || 'ctx') + '">' + esc(ln.text != null ? ln.text : ln) + '</div>';
    });
    if (git.truncated || lines.length > 300) h += '<div class="td-diff-ctx">… truncated</div>';
    return h + '</div>';
  }

  var _fileCache = {};
  function _loadFile(path, content) {
    if (!path) return;
    var apply = function (d) {
      var g = document.getElementById('td-git');
      if (g) g.innerHTML = _diffHtml(d && d.git);
      var a = document.getElementById('td-ast');
      if (a) {
        var ast = (d && d.ast) || {};
        var syms = ast.available ? ast.symbols : null;
        var rows = Array.isArray(syms) ? syms
          : (syms && Array.isArray(syms.rows) ? syms.rows
          : (syms && Array.isArray(syms.nodes) ? syms.nodes : []));
        if (ast.available && rows.length) {
          a.innerHTML = rows.slice(0, 50).map(function (s) {
            var nm = s.qualified_name || s.name || s.id || (s.properties && s.properties.name) || '?';
            return '<div class="conn-item"><span class="conn-label">' + esc(nm) + '</span></div>';
          }).join('') + (rows.length > 50 ? '<div class="conn-item">… ' + (rows.length - 50) + ' more</div>' : '');
        } else {
          a.innerHTML = '<div class="conn-item" style="color:var(--text-dim)">no AST · '
            + esc((ast.reason || ast.error) || 'not indexed') + '</div>';
        }
      }
    };
    if (_fileCache[path]) { apply(_fileCache[path]); return; }
    _fetch('/api/trace/file?path=' + encodeURIComponent(path))
      .then(function (d) { _fileCache[path] = d; apply(d); })
      .catch(function () {
        var g = document.getElementById('td-git'); if (g) g.textContent = 'diff unavailable';
      });
  }

  window.JUG = window.JUG || {};
  window.JUG._traceDetail = { build: build, wire: wire };
})();
