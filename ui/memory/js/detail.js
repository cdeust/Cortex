// Cortex Memory Dashboard — Detail Panel
(function() {
  var CMD = window.CMD;
  var esc, grid, row;

  CMD.closePanel = function() {
    document.getElementById('panel').classList.remove('open');
    if (CMD.selectedNode) {
      CMD.selectedNode._mesh.material.emissiveIntensity = CMD.selectedNode._baseEmit;
      CMD.selectedNode = null;
    }
    CMD.clearConnectionHighlights();
  };

  function makeGrid() { var g = document.createElement('div'); g.className = 'meta-grid'; return g; }
  function addRow(g, l, v, c) { g.innerHTML += '<div class="ml">' + l + '</div><div class="mv"' + (c ? ' style="color:' + c + '"' : '') + '>' + CMD.escHtml(String(v)) + '</div>'; }
  function makeSec(label, body) { var s = document.createElement('div'); s.className = 'panel-section'; s.innerHTML = '<div class="panel-label">' + label + '</div>' + body; return s; }

  CMD.openPanel = function(n) {
    // Benchmark nodes have their own renderer
    if (CMD.openPanelBenchmark && CMD.openPanelBenchmark(n)) return;

    if (CMD.selectedNode) CMD.selectedNode._mesh.material.emissiveIntensity = CMD.selectedNode._baseEmit;
    CMD.selectedNode = n;
    n._mesh.material.emissiveIntensity = n._baseEmit * 2;
    CMD.highlightConnections(n.id);
    var hexCol = '#' + CMD.nodeColor(n).getHexString();

    var typeMap = { 'memory-index':'MEM INDEX','project-file':'CLAUDE.MD','project-hub':'PROJECT HUB','settings':'SETTINGS','global-instruction':'GLOBAL','plan':'PLAN','mcp-tool':'MCP TOOL','plugin':'PLUGIN','todo':'TODO','conversation':'CHATLOG','memory':(n.type||'memory').toUpperCase() };
    var typeEl = document.getElementById('panel-type');
    typeEl.textContent = typeMap[n.nodeType] || (n.nodeType || '').toUpperCase().replace(/-/g, ' ');
    typeEl.style.color = hexCol; typeEl.style.borderColor = hexCol + '55';

    var catEl = document.getElementById('panel-cat');
    if (n.category && CMD.CATEGORY_COLORS[n.category]) { var cc = CMD.CATEGORY_COLORS[n.category]; catEl.textContent = n.category; catEl.style.cssText = 'display:inline-block;color:' + cc + ';background:' + cc + '22;border-color:' + cc + '44'; }
    else { catEl.style.display = 'none'; catEl.textContent = ''; }

    document.getElementById('panel-name').textContent = n.name || n.id;
    document.getElementById('panel-proj').textContent = CMD.cleanProject(n.project);
    var statusColors = { active:'#26de81', archived:'rgba(255,255,255,0.25)', pinned:'#ffca28' };
    document.getElementById('panel-status').innerHTML = '<span style="color:' + (statusColors[n.status||'active']||'#666') + '">\u25cf</span> ' + (n.status||'active');

    var tagsEl = document.getElementById('panel-tags'); tagsEl.innerHTML = '';
    (n.tags || []).forEach(function(t) { var p = document.createElement('span'); p.className = 'tag-pill'; p.textContent = t; tagsEl.appendChild(p); });

    var metaEl = document.getElementById('panel-meta');
    if (n.nodeType === 'conversation') { var parts = []; if (n.startedAt) parts.push(new Date(n.startedAt).toLocaleString()); if (n.startedAt && n.endedAt) parts.push(CMD.formatDuration(n.startedAt, n.endedAt)); metaEl.textContent = parts.join(' \xb7 '); }
    else { var parts = []; if (n.modifiedAt) parts.push(new Date(n.modifiedAt).toLocaleDateString()); if (n.file) parts.push(n.file.split('/').slice(-2).join('/')); metaEl.textContent = parts.join(' \xb7 '); }

    document.getElementById('panel-desc').textContent = n.description || '';
    var content = document.getElementById('panel-content'); content.innerHTML = '';
    CMD._renderPanelContent(n, content);

    var connIds = CMD.edges.filter(function(e) { return e.source === n.id || e.target === n.id; })
      .map(function(e) { return e.source === n.id ? e.target : e.source; })
      .filter(function(id) { var x = CMD.nodeMap[id]; return x && x.nodeType !== 'conversation'; }).slice(0, 8);
    if (connIds.length) {
      content.appendChild(makeSec('Connected', connIds.map(function(id) { var x = CMD.nodeMap[id]; var c = '#' + CMD.nodeColor(x).getHexString(); return '<div class="panel-stat"><span class="k" style="color:' + c + '">' + (x.nodeType||'').replace(/-/g,' ') + '</span><span class="v">' + CMD.escHtml(x.name||id) + '</span></div>'; }).join('')));
    }
    document.getElementById('panel').classList.add('open');
  };

  CMD._renderPanelContent = function(n, ct) {
    if (n.nodeType === 'conversation') renderConv(n, ct);
    else if (n.nodeType === 'project-hub') renderHub(n, ct);
    else if (n.nodeType === 'plan') renderPlan(n, ct);
    else if (n.nodeType === 'mcp-tool') renderTool(n, ct);
    else if (n.nodeType === 'plugin') renderPlugin(n, ct);
    else if (n.nodeType === 'todo') renderTodo(n, ct);
    else if (n.nodeType === 'settings' && n.body) renderSettings(n, ct);
    else if (n.nodeType === 'memory' && n.id && n.id.startsWith('m_')) renderMemory(n, ct);
    else if (n.body) ct.appendChild(makeSec('Content', '<div class="panel-body">' + CMD.escHtml(n.body.slice(0, 800)) + (n.body.length > 800 ? '\n\u2026' : '') + '</div>'));
  };

  function renderConv(n, ct) {
    var g = makeGrid();
    if (n.messageCount) { var u = Math.round(n.messageCount / 2); addRow(g, 'Messages', n.messageCount + ' (' + u + ' user, ' + (n.messageCount - u) + ' asst)'); }
    addRow(g, 'Duration', CMD.formatDuration(n.startedAt, n.endedAt));
    if (n.turnCount) addRow(g, 'Turns', n.turnCount);
    if (n.fileSize) addRow(g, 'Size', (n.fileSize / 1048576).toFixed(1) + ' MB');
    if (n.gitBranch) addRow(g, 'Branch', n.gitBranch);
    if (n.toolsUsed && n.toolsUsed.length) addRow(g, 'Tools', n.toolsUsed.join(', '));
    if (n.cwd) addRow(g, 'CWD', n.cwd.replace(/^\/Users\/[^/]+\//, '~/'));
    ct.appendChild(g);
    var sec = document.createElement('div'); sec.className = 'panel-section';
    sec.innerHTML = '<div class="panel-label">Messages</div><div id="panel-msgs" style="font-size:9px;color:rgba(255,255,255,.2)">Loading\u2026</div>';
    ct.appendChild(sec);
    fetch('/api/detail?id=' + encodeURIComponent(n.sessionId || n.id)).then(function(r) { if (!r.ok) throw new Error(); return r.json(); }).then(function(data) {
      var msgs = data.messages || [], el = document.getElementById('panel-msgs');
      if (!el) return; if (!msgs.length) { el.textContent = 'No messages.'; return; }
      var uM = msgs.filter(function(m) { return m.role === 'user'; }), aM = msgs.filter(function(m) { return m.role === 'assistant'; });
      var html = ''; if (data.summary) html += '<div style="font-size:9px;color:rgba(255,255,255,0.4);line-height:1.6;border-left:2px solid rgba(255,255,255,0.1);padding-left:8px;margin-bottom:10px">' + CMD.escHtml(data.summary.slice(0, 300)) + '</div>';
      html += '<div style="font-size:8px;color:rgba(255,255,255,0.2);margin-bottom:8px">' + uM.length + ' prompts \xb7 ' + aM.length + ' responses</div>';
      msgs.slice(0, 30).forEach(function(m) {
        var isU = m.role === 'user', label = isU ? '\u25b6 You' : '\u25c0 Claude' + (m.model ? ' (' + m.model.split('-').slice(0, 3).join('-') + ')' : '');
        html += '<div class="msg-bubble ' + m.role + '"><div class="msg-role">' + label + '</div>';
        if (m.content) html += '<div style="font-size:9px;color:rgba(255,255,255,0.45);line-height:1.5">' + CMD.escHtml(m.content.slice(0, 220)) + (m.content.length > 220 ? '\u2026' : '') + '</div>';
        if (m.tools && m.tools.length) { html += '<ul class="tool-list">'; m.tools.forEach(function(t) { html += '<li class="tool-item"><span class="tool-name">' + CMD.escHtml(t.tool) + '</span>' + (t.input ? '<span class="tool-input">' + CMD.escHtml(t.input.slice(0, 70)) + (t.input.length > 70 ? '\u2026' : '') + '</span>' : '') + '</li>'; }); html += '</ul>'; }
        var mp = []; if (m.timestamp) mp.push(new Date(m.timestamp).toLocaleTimeString());
        if (m.inputTokens || m.outputTokens) { var tp = []; if (m.inputTokens) tp.push('\u2191' + (m.inputTokens > 1000 ? (m.inputTokens / 1000).toFixed(1) + 'K' : m.inputTokens)); if (m.outputTokens) tp.push('\u2193' + (m.outputTokens > 1000 ? (m.outputTokens / 1000).toFixed(1) + 'K' : m.outputTokens)); mp.push(tp.join(' ') + ' tok'); }
        if (mp.length) html += '<div class="msg-meta">' + mp.join(' \xb7 ') + '</div>';
        html += '</div>';
      });
      if (msgs.length > 30) html += '<div style="font-size:8px;color:rgba(255,255,255,.12);padding:4px 0">+ ' + (msgs.length - 30) + ' more</div>';
      el.innerHTML = html;
    }).catch(function() { var el = document.getElementById('panel-msgs'); if (el) el.textContent = '\u2014'; });
  }

  function renderHub(n, ct) {
    var members = CMD.nodes.filter(function(x) { return x.project === n.project && x.nodeType !== 'project-hub'; });
    var counts = {}; members.forEach(function(x) { counts[x.nodeType] = (counts[x.nodeType] || 0) + 1; });
    var g = makeGrid();
    Object.entries(counts).sort(function(a, b) { return b[1] - a[1]; }).forEach(function(pair) {
      var col = '#' + CMD.nodeColor({ nodeType: pair[0], type: pair[0] }).getHexString();
      g.innerHTML += '<div class="ml" style="color:' + col + '">' + pair[0].replace(/-/g, ' ') + '</div><div class="mv">' + pair[1] + '</div>';
    }); ct.appendChild(g);
  }

  function renderPlan(n, ct) {
    if (n.sections && n.sections.length) ct.appendChild(makeSec('Sections', n.sections.map(function(s) { return '<div style="font-size:9px;color:rgba(255,255,255,0.55);padding:2px 0">\xa7 ' + CMD.escHtml(s) + '</div>'; }).join('')));
    if (n.body) ct.appendChild(makeSec('Content', '<div class="panel-body">' + CMD.escHtml(n.body.slice(0, 1000)) + (n.body.length > 1000 ? '\n\u2026' : '') + '</div>'));
  }

  function renderTool(n, ct) {
    var g = makeGrid();
    if (n.command) addRow(g, 'Command', n.command); if (n.args && n.args.length) addRow(g, 'Args', n.args.join(' '));
    if (n.cwd) addRow(g, 'Project', n.cwd.replace(/^\/Users\/[^/]+\//, '~/')); if (n.env && Object.keys(n.env).length) addRow(g, 'Env', Object.keys(n.env).join(', '));
    ct.appendChild(g);
    if (n.body) ct.appendChild(makeSec('Config', '<div class="panel-body" style="font-family:monospace;font-size:9px">' + CMD.escHtml(n.body.slice(0, 500)) + '</div>'));
  }

  function renderPlugin(n, ct) {
    var g = makeGrid(); addRow(g, 'Plugin ID', n.pluginId || n.name || '\u2014'); addRow(g, 'Version', n.version || '?'); addRow(g, 'Scope', n.scope || 'user');
    if (n.installedAt) addRow(g, 'Installed', new Date(n.installedAt).toLocaleDateString()); ct.appendChild(g);
  }

  function renderTodo(n, ct) {
    var items = n.items || [];
    ct.appendChild(makeSec('Items', items.map(function(item) {
      var icon = item.status === 'completed' ? '\u2713' : item.status === 'in_progress' ? '\u25ce' : '\u25cb';
      var col = item.status === 'completed' ? '#26de81' : item.status === 'in_progress' ? '#ffca28' : 'rgba(255,255,255,0.3)';
      return '<div class="todo-item"><span style="color:' + col + ';flex-shrink:0">' + icon + '</span><span style="color:rgba(255,255,255,0.45)">' + CMD.escHtml(item.content || '') + '</span></div>';
    }).join('') || '<div style="font-size:9px;color:rgba(255,255,255,0.2)">No items</div>'));
  }

  function renderSettings(n, ct) {
    var bodyHtml = '';
    try { var p = JSON.parse(n.body); if (p.enabledPlugins) { bodyHtml += '<div style="font-size:8px;color:rgba(255,255,255,0.3);margin-bottom:3px">Enabled plugins:</div>'; Object.keys(p.enabledPlugins).forEach(function(k) { bodyHtml += '<div style="font-size:9px;color:rgba(255,255,255,0.5);padding:1px 0">\u25b8 ' + CMD.escHtml(k) + '</div>'; }); }
    if (p.skipDangerousModePermissionPrompt) bodyHtml += '<div style="font-size:9px;color:rgba(255,100,50,0.8);margin-top:4px">\u26a0 Dangerous mode enabled</div>';
    } catch (_) { bodyHtml = '<div class="panel-body">' + CMD.escHtml((n.body || '').slice(0, 400)) + '</div>'; }
    ct.appendChild(makeSec('Configuration', bodyHtml));
  }

  function renderMemory(n, ct) {
    var g = makeGrid();
    addRow(g, 'Heat', (n.heat || 0).toFixed(3)); addRow(g, 'Importance', (n.importance || 0.5).toFixed(3));
    addRow(g, 'Store', n.store_type || '\u2014'); addRow(g, 'Stage', n.consolidation_stage || 'labile', CMD.STAGE_COLORS[n.consolidation_stage] || '#666');
    addRow(g, 'H\u2192C Dep.', (n.hippocampal_dependency || 1).toFixed(2));
    if (n.schema_match_score > 0) addRow(g, 'Schema', (n.schema_match_score).toFixed(2));
    if (n.interference_score > 0) addRow(g, 'Interference', (n.interference_score).toFixed(3), '#ff4444');
    if (n.theta_phase > 0) addRow(g, '\u03b8 Phase', (n.theta_phase).toFixed(3));
    addRow(g, 'Source', n.source || '\u2014'); addRow(g, 'Accesses', n.access_count || 0);
    ct.appendChild(g);
    if (n.name) ct.appendChild(makeSec('Content', '<div class="panel-body">' + CMD.escHtml((n.name || '').slice(0, 600)) + ((n.name || '').length > 600 ? '\n\u2026' : '') + '</div>'));
  }
})();
