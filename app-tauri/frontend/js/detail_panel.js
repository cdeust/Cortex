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
      // Gap 6: preserve edge-level confidence + reason so the detail
      // panel can show WHY an edge exists and how trustworthy it is.
      byType[t].push({
        node: other,
        weight: e.weight || 0,
        confidence: typeof e.confidence === 'number' ? e.confidence : null,
        reason: e.reason || null,
      });
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
      'has-discussion': 'Discussion in',
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
        var name = JUG._fmt.fullLabel(item.node.label || item.node.id);
        // Gap 6: show confidence + reason chips ONLY for heuristic
        // edges (calls / imports / unresolved). Structural defaults
        // ("100% direct-ast" / "100% memory-entities-link") are
        // tautological — rendering them on 8000 defined_in rows adds
        // pure visual noise. Suppress if both values match a known
        // structural default.
        var meta = '';
        var isStructuralDefault =
          item.confidence === 1.0 &&
          (item.reason === 'direct-ast' ||
           item.reason === 'memory-entities-link');
        if (!isStructuralDefault) {
          if (item.confidence != null) {
            var pct = Math.round(item.confidence * 100);
            meta += ' <span class="conn-confidence" title="Edge confidence">'
              + pct + '%</span>';
          }
          if (item.reason) {
            meta += ' <span class="conn-reason" title="Edge reason">'
              + JUG._fmt.esc(item.reason) + '</span>';
          }
        }
        h += '<div class="conn-item" data-node-id="' + item.node.id + '">' +
          '<span class="conn-dot" style="background:' + c + '"></span>' +
          '<span class="conn-label">' + JUG._fmt.esc(name) + '</span>' +
          meta + '</div>';
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

    var h = '';
    if (data.type === 'discussion') {
      h += JUG._fmt.header(data, col, typeLabel);
      h += JUG._fmt.quality(data);
      h += JUG._disc.buildDiscussionDetail(data);
      h += buildConnections(data, edges);
    } else {
      h += JUG._fmt.header(data, col, typeLabel);
      h += JUG._fmt.quality(data);
      h += JUG._fmt.gauges(data);
      h += JUG._fmt.content(data);
      h += JUG._fmt.tags(data.tags);
      h += buildEmotion(data);
      h += JUG._fmt.bioSection(data);
      h += buildConnections(data, edges);
      h += JUG._fmt.badges(data);
    }

    content.innerHTML = h;

    // Memory nodes get the rich emotion + meaning + explained
    // measurements panels (same components used in Knowledge cards) so
    // Board ticket details match Knowledge card details information
    // parity with plain-language explanations for every number.
    if (data && data.type === 'memory' && window.JUG && JUG._memSci) {
      if (typeof JUG._memSci.buildEmotionChip === 'function') {
        var emo = JUG._memSci.buildEmotionChip(data);
        if (emo) {
          emo.classList.add('ms-emotion--detail');
          content.appendChild(emo);
        }
      }
      if (typeof JUG._memSci.buildMeaningSection === 'function') {
        var meaning = JUG._memSci.buildMeaningSection(data);
        if (meaning) content.appendChild(meaning);
      }
      if (typeof JUG._memSci.buildExplainedPanel === 'function') {
        var explained = JUG._memSci.buildExplainedPanel(data);
        if (explained) content.appendChild(explained);
      }
    }

    panel.classList.add('open');
    wireInteractions(content);
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
    var viewBtn = content.querySelector('.disc-view-btn');
    if (viewBtn) {
      viewBtn.addEventListener('click', function() {
        JUG._disc.openConversationModal(viewBtn.dataset.sessionId);
      });
    }
    var rawBtn = document.getElementById('detail-raw-btn');
    if (rawBtn) {
      rawBtn.addEventListener('click', function() {
        var raw = document.getElementById('detail-raw-text');
        if (!raw) return;
        var hidden = raw.classList.toggle('hidden');
        rawBtn.textContent = hidden ? 'Show raw' : 'Hide raw';
      });
    }
  }

  function closeDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (panel) {
      panel.classList.remove('open');
      panel.classList.remove('minimized');
    }
  }

  // Event listeners
  JUG.on('graph:selectNode', function(node) { openDetailPanel(node); });
  JUG.on('graph:deselectNode', closeDetailPanel);

  function minimizeDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (!panel) return;
    panel.classList.remove('open');
    panel.classList.add('minimized');
  }

  function restoreDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (!panel) return;
    panel.classList.remove('minimized');
    panel.classList.add('open');
  }

  document.addEventListener('DOMContentLoaded', function() {
    // Minimize: slide panel down to peek bar, keep selection
    var minBtn = document.getElementById('minimize-detail');
    if (minBtn) minBtn.addEventListener('click', function() {
      minimizeDetailPanel();
    });

    // Peek bar: click to restore full panel
    var peekBar = document.getElementById('detail-peek');
    if (peekBar) peekBar.addEventListener('click', function() {
      restoreDetailPanel();
    });

    // Close: deselect node entirely
    var closeBtn = document.getElementById('close-detail');
    if (closeBtn) closeBtn.addEventListener('click', function() {
      JUG.deselectNode();
    });
  });

  window.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === 'Escape') {
      var panel = document.getElementById('detail-panel');
      if (panel && panel.classList.contains('open')) minimizeDetailPanel();
      else if (panel && panel.classList.contains('minimized')) {
        panel.classList.remove('minimized');
        JUG.deselectNode();
      }
    }
  });

  JUG.openDetailPanel = openDetailPanel;
  JUG.closeDetailPanel = closeDetailPanel;
})();
