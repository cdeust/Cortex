// Cortex Neural Graph — Detail Panel (2D force-graph)
(function() {

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function getConnections(node) {
    var edges = JUG._currentEdges || [];
    var connected = {};
    var connectedEdges = [];
    connected[node.id] = true;
    edges.forEach(function(e) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === node.id) { connected[tid] = true; connectedEdges.push(e); }
      if (tid === node.id) { connected[sid] = true; connectedEdges.push(e); }
    });
    return { nodeSet: connected, edges: connectedEdges };
  }

  function findNode(id) {
    var gd = JUG.getGraph ? JUG.getGraph().graphData() : { nodes: [] };
    for (var i = 0; i < gd.nodes.length; i++) {
      if (gd.nodes[i].id === id) return gd.nodes[i];
    }
    return null;
  }

  function openDetailPanel(data) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    if (!panel || !content) return;

    var col = JUG.getNodeColor(data);
    var typeLabel = JUG.NODE_LABELS[data.type] || data.type;
    var conn = getConnections(data);

    var h = '<div class="node-badge" style="background:' + col + '10;border-color:' + col + '40;color:' + col + '">' +
      '<span style="width:5px;height:5px;border-radius:50%;background:' + col + ';display:inline-block;box-shadow:0 0 6px ' + col + '"></span> ' +
      typeLabel + '</div>';

    h += '<h2>' + escapeHtml(data.label || '') + '</h2>';
    h += '<div class="domain-label">' + escapeHtml(data.domain || '') + '</div>';
    h += '<div style="font-size:7px;color:var(--text-dim);margin-bottom:12px">ID: ' + data.id + '</div>';

    // Quality score
    if (data.quality !== undefined) {
      var q = data.quality;
      var qColor = q >= 0.6 ? 'var(--green, #40D870)' : q >= 0.3 ? 'var(--amber, #E0B040)' : 'var(--red, #E05050)';
      var qWord = q >= 0.7 ? 'Strong' : q >= 0.5 ? 'Good' : q >= 0.3 ? 'Moderate' : 'Weak';
      h += '<div class="section-title">Quality Assessment</div>';
      h += '<div class="bio-state">';
      h += '<div class="bio-row"><span class="bio-label">Score</span>' +
        '<span class="bio-val" style="color:' + qColor + '">' + (q * 100).toFixed(0) + '% — ' + qWord + '</span></div>';
      h += '<div class="bio-row"><span class="bio-label">&nbsp;</span>' +
        '<div class="bio-bar"><div class="bio-fill" style="width:' + (q * 100) + '%;background:' + qColor + '"></div></div></div>';
      if (data.qualityLabel) {
        h += '<div style="font-size:7px;color:var(--text-dim);margin-top:4px;line-height:1.4">' + escapeHtml(data.qualityLabel) + '</div>';
      }
      h += '</div>';
    }

    // Metrics
    var metrics = [];
    if (data.recall_10 !== undefined) metrics.push(['Recall@10', Math.round(data.recall_10), '%']);
    if (data.mrr !== undefined) metrics.push(['MRR', (data.mrr * 1000 | 0) / 10, '%']);
    if (data.paper_best !== undefined) metrics.push(['Paper Best', Math.round(data.paper_best), '%']);
    if (data.questions !== undefined) metrics.push(['Questions', data.questions, '']);
    if (data.sessionCount !== undefined) metrics.push(['Sessions', data.sessionCount, '']);
    if (data.heat !== undefined) metrics.push(['Heat', Math.round(data.heat * 100), '%']);
    if (data.importance !== undefined) metrics.push(['Importance', Math.round(data.importance * 100), '%']);
    if (data.confidence !== undefined) metrics.push(['Confidence', Math.round(data.confidence * 100), '%']);
    if (data.frequency !== undefined) metrics.push(['Frequency', data.frequency, 'x']);
    if (data.ratio !== undefined) metrics.push(['Usage', Math.round(data.ratio * 100), '%']);
    if (data.accessCount) metrics.push(['Accesses', data.accessCount, '']);
    if (data.activation !== undefined) metrics.push(['Activation', data.activation.toFixed(3), '']);
    if (data.avgPerSession !== undefined) metrics.push(['Avg/Sess', data.avgPerSession, '']);

    if (metrics.length) {
      h += '<div class="section-title">Metrics</div><div class="metric-grid">';
      metrics.forEach(function(m) {
        h += '<div class="metric-card"><div class="metric-label">' + m[0] + '</div>' +
          '<div class="metric-val">' + m[1] + '<span class="metric-unit">' + m[2] + '</span></div></div>';
      });
      h += '</div>';
    }

    // Content
    if (data.content) {
      var contentLabel = data.type === 'memory' ? 'Content'
        : data.type === 'entity' ? 'Entity'
        : data.type === 'recurring-pattern' ? 'Pattern Keywords'
        : data.type === 'entry-point' ? 'Entry Pattern'
        : data.type === 'tool-preference' ? 'Tool Details'
        : data.type === 'behavioral-feature' ? 'Feature Details'
        : data.type === 'domain' ? 'Domain Summary' : 'Details';
      h += '<div class="section-title">' + contentLabel + '</div>';
      h += '<div class="detail-content-block">' + escapeHtml(data.content) + '</div>';
    }

    // Tags
    if (data.tags && data.tags.length) {
      h += '<div class="section-title">Tags</div><div style="display:flex;flex-wrap:wrap;gap:4px">';
      data.tags.forEach(function(t) { h += '<span class="detail-tag">' + escapeHtml(t) + '</span>'; });
      h += '</div>';
    }

    // Connections
    if (conn.edges.length > 0) {
      // Group by edge type
      var byType = {};
      conn.edges.forEach(function(e) {
        var sid = typeof e.source === 'object' ? e.source.id : e.source;
        var tid = typeof e.target === 'object' ? e.target.id : e.target;
        var otherId = sid === data.id ? tid : sid;
        var otherNode = findNode(otherId);
        if (!otherNode) return;
        var t = e.type || 'related';
        if (!byType[t]) byType[t] = [];
        byType[t].push({ node: otherNode, weight: e.weight || 0 });
      });

      h += '<div class="section-title">Connections (' + conn.edges.length + ')</div>';
      Object.keys(byType).sort().forEach(function(edgeType) {
        var items = byType[edgeType];
        var edgeColor = JUG.EDGE_COLORS[edgeType] || '#90a4ae';
        h += '<div class="conn-group">';
        h += '<div class="conn-type" style="color:' + edgeColor + '">' +
          edgeType.replace(/_/g, ' ') + ' <span class="conn-count">' + items.length + '</span></div>';
        items.forEach(function(item) {
          var otherColor = JUG.getNodeColor(item.node);
          h += '<div class="conn-item" data-node-id="' + item.node.id + '">';
          h += '<span class="conn-dot" style="background:' + otherColor + '"></span>';
          h += '<span class="conn-label">' + escapeHtml(item.node.label || item.node.id) + '</span>';
          h += '<span class="conn-weight">' + item.weight.toFixed(2) + '</span>';
          h += '</div>';
        });
        h += '</div>';
      });
    }

    // Biological state
    var emoColors = { urgency: '#ff3366', frustration: '#ef4444', satisfaction: '#22c55e', discovery: '#f59e0b', confusion: '#8b5cf6' };
    if (data.emotion && data.emotion !== 'neutral') {
      var emoColor = emoColors[data.emotion] || '#90a4ae';
      h += '<div class="section-title">Biological State</div><div class="bio-state">';
      h += '<div class="bio-row"><span class="bio-label">Emotion</span>' +
        '<span class="bio-val" style="color:' + emoColor + '">' + data.emotion.toUpperCase() + '</span></div>';
      if (data.arousal !== undefined) {
        h += '<div class="bio-row"><span class="bio-label">Arousal</span>' +
          '<span class="bio-val">' + Math.round(data.arousal * 100) + '%</span>' +
          '<div class="bio-bar"><div class="bio-fill" style="width:' + (data.arousal * 100) + '%;background:' + emoColor + '"></div></div></div>';
      }
      if (data.valence !== undefined) {
        h += '<div class="bio-row"><span class="bio-label">Valence</span>' +
          '<span class="bio-val">' + (data.valence > 0 ? '+' : '') + data.valence.toFixed(2) + '</span></div>';
      }
      if (data.emotionalBoost !== undefined && data.emotionalBoost > 1.01) {
        h += '<div class="bio-row"><span class="bio-label">Importance Boost</span>' +
          '<span class="bio-val" style="color:var(--amber)">' + data.emotionalBoost.toFixed(2) + 'x</span></div>';
      }
      h += '</div>';
    }

    // Badges
    var badges = [];
    if (data.isGlobal) badges.push('<span class="detail-badge" style="color:#FF4081;border-color:#FF408140;background:#FF408110">\ud83c\udf10 GLOBAL</span>');
    if (data.isProtected) badges.push('<span class="detail-badge badge-anchor">ANCHORED</span>');
    if (data.storeType) badges.push('<span class="detail-badge badge-store">' + data.storeType.toUpperCase() + '</span>');
    if (data.entityType) badges.push('<span class="detail-badge badge-entity">' + data.entityType.toUpperCase() + '</span>');
    if (data.emotion && data.emotion !== 'neutral') {
      badges.push('<span class="detail-badge" style="color:' + (emoColors[data.emotion] || '#90a4ae') +
        ';border-color:' + (emoColors[data.emotion] || '#90a4ae') + '40">' + data.emotion.toUpperCase() + '</span>');
    }
    if (badges.length) h += '<div style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">' + badges.join('') + '</div>';

    content.innerHTML = h;
    panel.classList.add('open');

    // Wire connection clicks
    content.querySelectorAll('.conn-item[data-node-id]').forEach(function(el) {
      el.addEventListener('click', function() {
        JUG.selectNodeById(el.dataset.nodeId);
      });
    });
  }

  function closeDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (panel) panel.classList.remove('open');
  }

  // Event listeners
  JUG.on('graph:selectNode', function(node) { openDetailPanel(node); });
  JUG.on('graph:deselectNode', closeDetailPanel);

  document.addEventListener('DOMContentLoaded', function() {
    var closeBtn = document.getElementById('close-detail');
    if (closeBtn) closeBtn.addEventListener('click', function() { JUG.deselectNode(); });
  });

  window.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') JUG.deselectNode();
  });

  JUG.openDetailPanel = openDetailPanel;
  JUG.closeDetailPanel = closeDetailPanel;
})();
