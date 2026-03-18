// JARVIS Memory Dashboard — Interaction Layer
// Detail panel and tooltip — raycasting handled by graph.js.

(function() {
  var tooltip = document.getElementById('tooltip');
  var panel = document.getElementById('panel');
  var mouse = { x: 0, y: 0 };

  addEventListener('mousemove', function(e) {
    mouse.x = e.clientX; mouse.y = e.clientY;
    if (tooltip.style.display === 'block') {
      var tx = e.clientX + 16, ty = e.clientY + 16;
      if (tx + 280 > innerWidth) tx = e.clientX - 294;
      if (ty + 100 > innerHeight) ty = innerHeight - 100;
      tooltip.style.left = tx + 'px';
      tooltip.style.top = ty + 'px';
    }
  });

  // ─── Tooltip ──────────────────────────────────────────────────
  JMD.on('graph:showTooltip', function(e) {
    var nd = e.node;
    var d = nd.data;
    var isEntity = nd.isEntity;

    var typeLabel = isEntity ? 'ENTITY' : (d.store_type || 'episodic').toUpperCase();
    var content = isEntity ? (d.name || '') : (d.content || '').slice(0, 120);
    var meta = isEntity
      ? (d.type || '') + ' \u00b7 heat ' + (d.heat || 0).toFixed(2)
      : JMD.timeAgo(d.created_at) + ' \u00b7 heat ' + (d.heat || 0).toFixed(2) + ' \u00b7 ' + (d.domain || '');

    var colorMap = { episodic: '#26de81', semantic: '#d946ef', entity: '#00d2ff' };
    var color = colorMap[nd.storeType] || '#00d2ff';

    tooltip.querySelector('.tt-label').textContent = content;
    tooltip.querySelector('.tt-type').textContent = typeLabel;
    tooltip.querySelector('.tt-type').style.color = color;
    tooltip.querySelector('.tt-meta').textContent = meta;
    tooltip.style.display = 'block';

    var tx = (e.x || mouse.x) + 16, ty = (e.y || mouse.y) + 16;
    if (tx + 280 > innerWidth) tx = (e.x || mouse.x) - 294;
    if (ty + 100 > innerHeight) ty = innerHeight - 100;
    tooltip.style.left = tx + 'px';
    tooltip.style.top = ty + 'px';
  });

  JMD.on('graph:hideTooltip', function() {
    tooltip.style.display = 'none';
  });

  // ─── Detail Panel ─────────────────────────────────────────────
  JMD.on('graph:openPanel', function(nd) {
    var d = nd.data;
    var isEntity = nd.isEntity;

    var colorMap = { episodic: '#26de81', semantic: '#d946ef', entity: '#00d2ff' };
    var color = colorMap[nd.storeType] || '#00d2ff';

    // Type badge
    var typeEl = document.getElementById('panel-type');
    typeEl.textContent = isEntity ? 'ENTITY' : (d.store_type || 'EPISODIC').toUpperCase();
    typeEl.style.color = color;
    typeEl.style.borderColor = color;
    typeEl.style.background = hexToRgba(color, 0.08);

    // Name/Content
    document.getElementById('panel-name').textContent = isEntity
      ? (d.name || 'Unknown Entity')
      : (d.content || '').slice(0, 300);

    // Metadata grid
    var meta = document.getElementById('panel-meta');
    if (isEntity) {
      meta.innerHTML = buildMetaGrid({
        'Type': d.type || 'unknown',
        'Heat': (d.heat || 0).toFixed(4),
        'Domain': d.domain || '\u2014',
      });
    } else {
      meta.innerHTML = buildMetaGrid({
        'Heat': (d.heat || 0).toFixed(4),
        'Importance': (d.importance || 0).toFixed(4),
        'Domain': d.domain || '\u2014',
        'Source': d.source || '\u2014',
        'Created': JMD.timeAgo(d.created_at),
        'Accessed': d.access_count || 0,
      });
    }

    // Tags
    var tagsEl = document.getElementById('panel-tags');
    var tags = d.tags || [];
    tagsEl.innerHTML = tags.map(function(t) {
      return '<span class="tag-pill">' + JMD.escHtml(t) + '</span>';
    }).join('');

    // Heat bar
    var heatBar = document.getElementById('panel-heat-bar');
    var heat = d.heat || 0;
    heatBar.style.width = (heat * 100) + '%';
    heatBar.style.background = 'linear-gradient(90deg, var(--accent-green), ' + JMD.heatColorCSS(heat) + ')';

    // Connections list
    buildConnectionsList(nd);

    panel.classList.add('open');
  });

  function hexToRgba(hex, alpha) {
    if (hex.charAt(0) === '#') hex = hex.slice(1);
    var r = parseInt(hex.slice(0,2), 16);
    var g = parseInt(hex.slice(2,4), 16);
    var b = parseInt(hex.slice(4,6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  function buildConnectionsList(nd) {
    var connEl = document.getElementById('panel-connections');
    if (!connEl) return;

    var nodeIdx = -1;
    for (var i = 0; i < JMD.allNodes.length; i++) {
      if (JMD.allNodes[i] === nd) { nodeIdx = i; break; }
    }
    if (nodeIdx < 0) { connEl.innerHTML = '<div class="conn-empty">No connections</div>'; return; }

    var edgeMap = JMD.edgeNodeMap || {};
    var edgeIndices = edgeMap[nodeIdx] || [];
    var edges = JMD.getActiveEdges ? JMD.getActiveEdges() : [];

    if (edgeIndices.length === 0) {
      connEl.innerHTML = '<div class="conn-empty">No connections</div>';
      return;
    }

    var connections = [];
    edgeIndices.forEach(function(ei) {
      var e = edges[ei];
      if (!e) return;
      var otherIdx = e.srcIdx === nodeIdx ? e.tgtIdx : e.srcIdx;
      var other = JMD.allNodes[otherIdx];
      if (!other) return;
      connections.push({
        node: other, idx: otherIdx,
        weight: e.weight || 0, type: e.type || 'related',
        isCausal: e.isCausal || false,
      });
    });

    connections.sort(function(a, b) { return b.weight - a.weight; });

    var html = '';
    connections.forEach(function(c) {
      var d = c.node.data;
      var label = c.node.isEntity ? (d.name || 'Entity') : (d.content || '').slice(0, 60);
      var typeTag = c.isCausal ? 'causal' : c.type;
      var colorMap = { episodic: '#26de81', semantic: '#d946ef', entity: '#00d2ff' };
      var dotColor = colorMap[c.node.storeType] || '#00d2ff';
      html += '<div class="conn-item" data-idx="' + c.idx + '">'
            + '<span class="conn-dot" style="background:' + dotColor + '"></span>'
            + '<span class="conn-label">' + JMD.escHtml(label) + '</span>'
            + '<span class="conn-weight">W: ' + c.weight.toFixed(2) + '</span>'
            + '</div>';
    });
    connEl.innerHTML = html;

    connEl.querySelectorAll('.conn-item').forEach(function(el) {
      el.addEventListener('click', function() {
        var idx = parseInt(el.dataset.idx, 10);
        var node = JMD.allNodes[idx];
        if (node) JMD.emit('graph:openPanel', node);
      });
    });
  }

  JMD.on('graph:closePanel', function() {
    panel.classList.remove('open');
  });

  function buildMetaGrid(obj) {
    var html = '';
    for (var key in obj) {
      html += '<div class="ml">' + JMD.escHtml(key) + '</div>';
      html += '<div class="mv">' + JMD.escHtml(String(obj[key])) + '</div>';
    }
    return html;
  }

  // Close button
  document.getElementById('panel-close').addEventListener('click', function() {
    JMD.emit('graph:closePanel');
    if (JMD.resetCamera) JMD.resetCamera();
  });

  // ─── Keyboard shortcuts ─────────────────────────────────────
  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') {
      JMD.emit('graph:closePanel');
      if (JMD.resetCamera) JMD.resetCamera();
    }
    if (e.key === 'a' || e.key === 'A') {
      JMD.setState('analyticsOpen', !JMD.state.analyticsOpen);
    }
  });
})();
