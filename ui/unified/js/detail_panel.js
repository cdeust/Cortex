// Cortex Neural Graph — Detail Panel
// Uses JUG._fmt (detail_format.js) for human-readable rendering
(function() {

  function getConnections(node) {
    var edges = JUG._currentEdges || [];
    var result = [];
    edges.forEach(function(e) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === node.id || tid === node.id) result.push(e);
    });
    return result;
  }

  function findNode(id) {
    var gd = JUG.getGraph ? JUG.getGraph().graphData() : { nodes: [] };
    for (var i = 0; i < gd.nodes.length; i++) {
      if (gd.nodes[i].id === id) return gd.nodes[i];
    }
    return null;
  }

  // ── Emotion section ──

  function buildEmotion(data) {
    var colors = {
      urgency: '#ff3366', frustration: '#ef4444', satisfaction: '#22c55e',
      discovery: '#f59e0b', confusion: '#8b5cf6',
    };
    if (!data.emotion || data.emotion === 'neutral') return '';
    var col = colors[data.emotion] || '#90a4ae';
    var labels = {
      urgency: 'This memory has a sense of urgency',
      frustration: 'This memory captures a frustrating moment',
      satisfaction: 'This memory reflects a positive outcome',
      discovery: 'This memory marks a discovery or insight',
      confusion: 'This memory involves uncertainty',
    };
    var h = '<div class="section-title">Emotional State</div>';
    h += '<div class="emo-card" style="border-color:' + col + '30">';
    h += '<div class="emo-name" style="color:' + col + '">' +
      data.emotion.charAt(0).toUpperCase() + data.emotion.slice(1) + '</div>';
    h += '<div class="emo-desc">' + (labels[data.emotion] || '') + '</div>';
    if (data.arousal !== undefined) {
      h += '<div class="emo-meter"><span>Intensity</span>' +
        '<div class="bio-bar"><div class="bio-fill" style="width:' +
        Math.round(data.arousal * 100) + '%;background:' + col +
        '"></div></div></div>';
    }
    h += '</div>';
    return h;
  }

  // ── Connections section ──

  function buildConnections(data, edges) {
    if (!edges.length) return '';
    var byType = {};
    edges.forEach(function(e) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      var otherId = sid === data.id ? tid : sid;
      var other = findNode(otherId);
      if (!other) return;
      var t = e.type || 'related';
      if (!byType[t]) byType[t] = [];
      byType[t].push({ node: other, weight: e.weight || 0 });
    });

    var friendlyEdge = {
      'memory-entity': 'Mentioned in',
      'domain-entity': 'Belongs to',
      'groups': 'Grouped under',
      'bridge': 'Cross-domain link',
      'co_occurrence': 'Often seen with',
      'caused_by': 'Caused by',
      'resolved_by': 'Resolved by',
      'imports': 'Imports',
      'calls': 'Calls',
    };

    var h = '<div class="section-title">Connections (' + edges.length + ')</div>';
    Object.keys(byType).sort().forEach(function(edgeType) {
      var items = byType[edgeType];
      var edgeColor = JUG.EDGE_COLORS[edgeType] || '#90a4ae';
      var label = friendlyEdge[edgeType] || edgeType.replace(/_/g, ' ');
      h += '<div class="conn-group">';
      h += '<div class="conn-type" style="color:' + edgeColor + '">' +
        label + ' <span class="conn-count">' + items.length + '</span></div>';
      items.forEach(function(item) {
        var c = JUG.getNodeColor(item.node);
        var name = JUG._fmt.cleanLabel(item.node.label || item.node.id);
        h += '<div class="conn-item" data-node-id="' + item.node.id + '">' +
          '<span class="conn-dot" style="background:' + c + '"></span>' +
          '<span class="conn-label">' + JUG._fmt.esc(name) + '</span></div>';
      });
      h += '</div>';
    });
    return h;
  }

  // ── Main panel builder ──

  function openDetailPanel(data) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    if (!panel || !content) return;

    var col = JUG.getNodeColor(data);
    var typeLabel = JUG.NODE_LABELS[data.type] || data.type;
    var edges = getConnections(data);

    var h = JUG._fmt.header(data, col, typeLabel);
    if (data.type === 'memory') {
      h += buildEditButton(data);
    }
    h += JUG._fmt.quality(data);
    h += JUG._fmt.gauges(data);
    h += JUG._fmt.content(data);
    h += JUG._fmt.tags(data.tags);
    h += buildEmotion(data);
    h += JUG._fmt.bioSection(data);
    h += buildConnections(data, edges);
    h += JUG._fmt.badges(data);

    content.innerHTML = h;
    panel.classList.add('open');
    wireInteractions(content);
    wireEditButton(content, data);
  }

  // ── Edit button ──

  function buildEditButton(data) {
    if (data.is_protected) return '';
    return '<button class="memory-edit-btn" id="memory-edit-toggle">Edit</button>';
  }

  function wireEditButton(container, data) {
    var btn = container.querySelector('#memory-edit-toggle');
    if (!btn) return;

    btn.addEventListener('click', function() {
      var existing = container.querySelector('.memory-edit-area');
      if (existing) { existing.remove(); btn.textContent = 'Edit'; return; }

      btn.textContent = 'Cancel';
      var rawId = (data.id || '').replace(/^memory-/, '');
      var contentText = data.content || '';

      var area = document.createElement('div');
      area.className = 'memory-edit-area';
      area.innerHTML =
        '<textarea class="memory-edit-textarea">' + JUG._fmt.esc(contentText) + '</textarea>' +
        '<div class="memory-edit-actions">' +
        '<button class="memory-edit-save">Save</button>' +
        '<span class="memory-edit-status"></span></div>';

      btn.parentNode.insertBefore(area, btn.nextSibling);

      area.querySelector('.memory-edit-save').addEventListener('click', function() {
        var ta = area.querySelector('.memory-edit-textarea');
        var status = area.querySelector('.memory-edit-status');
        var newContent = ta.value.trim();
        if (!newContent) { status.textContent = 'Content cannot be empty'; return; }

        status.textContent = 'Saving...';
        fetch('/api/memory', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ memory_id: parseInt(rawId), content: newContent })
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
          if (resp.error) {
            status.textContent = 'Error: ' + resp.error;
            status.style.color = '#E05050';
          } else {
            status.textContent = 'Saved';
            status.style.color = '#40D870';
            data.content = newContent;
            btn.textContent = 'Edit';
            setTimeout(function() { area.remove(); }, 800);
            JUG.emit('memory:updated', { id: data.id, content: newContent });
          }
        })
        .catch(function(err) {
          status.textContent = 'Network error';
          status.style.color = '#E05050';
        });
      });
    });
  }

  function wireInteractions(content) {
    content.querySelectorAll('.conn-item[data-node-id]').forEach(function(el) {
      el.addEventListener('click', function() {
        JUG.selectNodeById(el.dataset.nodeId);
      });
    });
    var expandBtn = document.getElementById('detail-expand-btn');
    if (expandBtn) {
      expandBtn.addEventListener('click', function() {
        var block = document.getElementById('detail-content-text');
        if (!block) return;
        var collapsed = block.classList.toggle('collapsed');
        expandBtn.textContent = collapsed ? 'Show more' : 'Show less';
      });
    }
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
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'Escape') JUG.deselectNode();
  });

  JUG.openDetailPanel = openDetailPanel;
  JUG.closeDetailPanel = closeDetailPanel;
})();
