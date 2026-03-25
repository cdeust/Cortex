// Cortex Neural Graph — Interaction
(function() {
  var raycaster = new THREE.Raycaster();
  var mouse = new THREE.Vector2();
  var hoveredIdx = -1;
  var tip = null;

  function getHoveredNode(clientX, clientY) {
    var container = document.getElementById('graph-container');
    if (!container) return null;
    var rect = container.getBoundingClientRect();
    var lx = clientX - rect.left;
    var ly = clientY - rect.top;
    if (lx < 0 || ly < 0 || lx > rect.width || ly > rect.height) return null;
    mouse.x = (lx / rect.width) * 2 - 1;
    mouse.y = -(ly / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, JUG.camera);

    var coreMeshes = [];
    for (var i = 0; i < JUG.allNodes.length; i++) {
      var n = JUG.allNodes[i];
      if (!n.group.visible) continue;
      var core = n.group.userData.coreMesh;
      if (core) coreMeshes.push(core);
    }

    var intersects = raycaster.intersectObjects(coreMeshes, false);
    if (intersects.length > 0) {
      var hit = intersects[0].object;
      for (var j = 0; j < JUG.allNodes.length; j++) {
        if (JUG.allNodes[j].group.userData.coreMesh === hit) {
          return { idx: j, node: JUG.allNodes[j] };
        }
      }
    }
    return null;
  }

  // ── Get connected nodes and edges for a given node index ──

  function getConnections(idx) {
    var connected = {};
    var connectedEdges = [];
    connected[idx] = true;
    var edges = JUG.getActiveEdges();
    var map = JUG.edgeNodeMap || {};
    (map[idx] || []).forEach(function(ei) {
      var e = edges[ei];
      if (e) {
        connected[e.srcIdx] = true;
        connected[e.tgtIdx] = true;
        connectedEdges.push(e);
      }
    });
    return { nodeSet: connected, edges: connectedEdges };
  }

  // ── Mouse events ──

  window.addEventListener('mousemove', function(e) {
    var hit = getHoveredNode(e.clientX, e.clientY);
    tip = document.getElementById('tooltip');

    if (hit) {
      document.body.style.cursor = 'pointer';
      hoveredIdx = hit.idx;
      JUG.highlightMesh.visible = true;
      JUG.highlightMesh.position.copy(hit.node.group.position);
      JUG.highlightMesh.scale.setScalar(hit.node.group.userData.baseScale * 1.8);
      JUG.highlightNodeEdges(hit.idx);
      showTooltip(hit.node.data, e.clientX, e.clientY);
    } else {
      document.body.style.cursor = 'default';
      JUG.highlightMesh.visible = false;
      if (hoveredIdx >= 0) {
        hoveredIdx = -1;
        if (JUG.state.selectedId === null) JUG.resetEdgeHighlight();
        hideTooltip();
      }
    }
  });

  window.addEventListener('click', function(e) {
    if (e.target.closest('#info-panel, #filter-bar, #detail-panel, #legend, #status-bar, #reset-btn, #monitor-panel, #monitor-toggle')) return;

    var hit = getHoveredNode(e.clientX, e.clientY);
    if (hit) {
      if (JUG.state.selectedId === hit.node.data.id) {
        deselectNode();
      } else {
        selectNode(hit.idx, hit.node);
      }
    } else if (JUG.state.selectedId !== null) {
      deselectNode();
    }
  });

  // ── Select by index (from graph click) ──

  function selectNode(idx, node) {
    JUG.state.selectedId = node.data.id;
    JUG.controls.autoRotate = false;
    JUG.highlightNodeEdges(idx);

    var conn = getConnections(idx);

    JUG.allNodes.forEach(function(n, i) {
      JUG.setGroupOpacity(n.group, conn.nodeSet[i] ? 1.0 : 0.08);
    });

    openDetailPanel(node.data, idx, conn);
    flyToNode(node);
  }

  // ── Select by ID (from monitor log click) ──

  function selectNodeById(nodeId) {
    for (var i = 0; i < JUG.allNodes.length; i++) {
      if (JUG.allNodes[i].data.id === nodeId) {
        selectNode(i, JUG.allNodes[i]);
        return true;
      }
    }
    return false;
  }

  function deselectNode() {
    JUG.state.selectedId = null;
    JUG.resetEdgeHighlight();
    JUG.allNodes.forEach(function(n) { JUG.setGroupOpacity(n.group, 1.0); });
    closeDetailPanel();
  }

  // ── Camera fly-to ──

  function flyToNode(node) {
    var pos = node.group.position;
    var dist = 80 + (node.data.size || 5) * 8;
    var targetPos = new THREE.Vector3(pos.x, pos.y, pos.z + dist);
    var targetLook = new THREE.Vector3(pos.x, pos.y, pos.z);
    var startPos = JUG.camera.position.clone();
    var startTarget = JUG.controls.target.clone();
    var startTime = performance.now();

    function step() {
      var t = Math.min((performance.now() - startTime) / 800, 1);
      var e = 1 - Math.pow(1 - t, 3);
      JUG.camera.position.lerpVectors(startPos, targetPos, e);
      JUG.controls.target.lerpVectors(startTarget, targetLook, e);
      JUG.controls.update();
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  }

  // ── Tooltip ──

  function showTooltip(data, x, y) {
    if (!tip) return;
    var label = document.getElementById('tt-label');
    var type = document.getElementById('tt-type');
    var meta = document.getElementById('tt-meta');
    if (label) label.textContent = data.label || '';
    if (type) {
      type.textContent = JUG.NODE_LABELS[data.type] || data.type;
      type.style.color = JUG.getNodeColor(data);
    }
    if (meta) {
      var m = [];
      if (data.domain) m.push('Domain: ' + data.domain);
      if (data.heat !== undefined) m.push('Heat: ' + data.heat);
      if (data.importance !== undefined) m.push('Importance: ' + data.importance);
      if (data.sessionCount !== undefined) m.push('Sessions: ' + data.sessionCount);
      if (data.confidence !== undefined) m.push('Confidence: ' + Math.round(data.confidence * 100) + '%');
      if (data.frequency !== undefined) m.push('Frequency: ' + data.frequency);
      if (data.ratio !== undefined) m.push('Usage: ' + Math.round(data.ratio * 100) + '%');
      if (data.entityType) m.push('Type: ' + data.entityType);
      meta.textContent = m.join('\n');
    }
    var tx = x + 16, ty = y + 16;
    if (tx + 260 > innerWidth) tx = x - 276;
    if (ty + 120 > innerHeight) ty = y - 136;
    tip.style.left = tx + 'px';
    tip.style.top = ty + 'px';
    tip.classList.add('visible');
  }

  function hideTooltip() {
    if (tip) tip.classList.remove('visible');
  }

  // ── Detail panel (right side) ──

  function openDetailPanel(data, idx, conn) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    if (!panel || !content) return;

    var col = JUG.getNodeColor(data);
    var typeLabel = JUG.NODE_LABELS[data.type] || data.type;

    var h = '<div class="node-badge" style="background:' + col + '10;border-color:' + col + '40;color:' + col + '">' +
      '<span style="width:5px;height:5px;border-radius:50%;background:' + col + ';display:inline-block;box-shadow:0 0 6px ' + col + '"></span> ' +
      typeLabel + '</div>';

    h += '<h2>' + escapeHtml(data.label || '') + '</h2>';
    h += '<div class="domain-label">' + escapeHtml(data.domain || '') + '</div>';

    // Node ID
    h += '<div style="font-size:7px;color:var(--text-dim);margin-bottom:12px;font-variant-numeric:tabular-nums">ID: ' + data.id + '</div>';

    // ── Metrics grid ──
    var metrics = [];
    if (data.sessionCount !== undefined) metrics.push(['Sessions', data.sessionCount, '']);
    if (data.heat !== undefined) metrics.push(['Heat', Math.round(data.heat * 100), '%']);
    if (data.importance !== undefined) metrics.push(['Importance', Math.round(data.importance * 100), '%']);
    if (data.confidence !== undefined) metrics.push(['Confidence', Math.round(data.confidence * 100), '%']);
    if (data.frequency !== undefined) metrics.push(['Frequency', data.frequency, 'x']);
    if (data.ratio !== undefined) metrics.push(['Usage', Math.round(data.ratio * 100), '%']);
    if (data.accessCount) metrics.push(['Accesses', data.accessCount, '']);
    if (data.activation !== undefined) metrics.push(['Activation', data.activation.toFixed(3), '']);
    if (data.avgPerSession !== undefined) metrics.push(['Avg/Sess', data.avgPerSession, '']);
    if (data.size !== undefined) metrics.push(['Size', data.size.toFixed(1), '']);

    if (metrics.length) {
      h += '<div class="section-title">Metrics</div><div class="metric-grid">';
      metrics.forEach(function(m) {
        h += '<div class="metric-card"><div class="metric-label">' + m[0] + '</div><div class="metric-val">' + m[1] + '<span class="metric-unit">' + m[2] + '</span></div></div>';
      });
      h += '</div>';
    }

    // ── Full content ──
    if (data.content) {
      var contentLabel = data.type === 'memory' ? 'Content'
        : data.type === 'entity' ? 'Entity'
        : data.type === 'recurring-pattern' ? 'Pattern Keywords'
        : data.type === 'entry-point' ? 'Entry Pattern'
        : data.type === 'tool-preference' ? 'Tool Details'
        : data.type === 'behavioral-feature' ? 'Feature Details'
        : data.type === 'domain' ? 'Domain Summary'
        : 'Details';
      h += '<div class="section-title">' + contentLabel + '</div>';
      h += '<div class="detail-content-block">' + escapeHtml(data.content) + '</div>';
    }

    // ── Tags ──
    if (data.tags && data.tags.length) {
      h += '<div class="section-title">Tags</div><div style="display:flex;flex-wrap:wrap;gap:4px">';
      data.tags.forEach(function(t) {
        h += '<span class="detail-tag">' + escapeHtml(t) + '</span>';
      });
      h += '</div>';
    }

    // ── Connections ──
    if (conn && conn.edges.length > 0) {
      // Group edges by type
      var byType = {};
      conn.edges.forEach(function(e) {
        var t = e.type || 'related';
        if (!byType[t]) byType[t] = [];
        var otherIdx = e.srcIdx === idx ? e.tgtIdx : e.srcIdx;
        var other = JUG.allNodes[otherIdx];
        if (other) {
          byType[t].push({
            label: other.data.label || other.data.id,
            type: other.data.type,
            color: JUG.getNodeColor(other.data),
            id: other.data.id,
            weight: e.weight,
          });
        }
      });

      h += '<div class="section-title">Connections (' + conn.edges.length + ')</div>';

      var types = Object.keys(byType).sort();
      types.forEach(function(edgeType) {
        var items = byType[edgeType];
        var edgeColor = JUG.EDGE_COLORS[edgeType] || '#90a4ae';
        h += '<div class="conn-group">';
        h += '<div class="conn-type" style="color:' + edgeColor + '">' + edgeType.replace(/_/g, ' ') + ' <span class="conn-count">' + items.length + '</span></div>';
        items.forEach(function(item) {
          h += '<div class="conn-item" data-node-id="' + item.id + '">';
          h += '<span class="conn-dot" style="background:' + item.color + '"></span>';
          h += '<span class="conn-label">' + escapeHtml(item.label) + '</span>';
          h += '<span class="conn-weight">' + (item.weight || 0).toFixed(2) + '</span>';
          h += '</div>';
        });
        h += '</div>';
      });
    }

    // ── Biological state ──
    if (data.emotion && data.emotion !== 'neutral') {
      h += '<div class="section-title">Biological State</div>';
      var emoColors = { urgency: '#ff3366', frustration: '#ef4444', satisfaction: '#22c55e', discovery: '#f59e0b', confusion: '#8b5cf6' };
      var emoColor = emoColors[data.emotion] || '#90a4ae';
      h += '<div class="bio-state">';
      h += '<div class="bio-row"><span class="bio-label">Emotion</span><span class="bio-val" style="color:' + emoColor + '">' + data.emotion.toUpperCase() + '</span></div>';
      if (data.arousal !== undefined) h += '<div class="bio-row"><span class="bio-label">Arousal</span><span class="bio-val">' + Math.round(data.arousal * 100) + '%</span><div class="bio-bar"><div class="bio-fill" style="width:' + (data.arousal * 100) + '%;background:' + emoColor + '"></div></div></div>';
      if (data.valence !== undefined) h += '<div class="bio-row"><span class="bio-label">Valence</span><span class="bio-val">' + (data.valence > 0 ? '+' : '') + data.valence.toFixed(2) + '</span></div>';
      if (data.emotionalBoost !== undefined && data.emotionalBoost > 1.01) h += '<div class="bio-row"><span class="bio-label">Importance Boost</span><span class="bio-val" style="color:var(--amber)">' + data.emotionalBoost.toFixed(2) + 'x</span></div>';
      if (data.decayResistance !== undefined && data.decayResistance > 1.01) h += '<div class="bio-row"><span class="bio-label">Decay Resistance</span><span class="bio-val" style="color:var(--green)">' + data.decayResistance.toFixed(2) + 'x</span></div>';
      h += '</div>';
    }

    // ── Status badges ──
    var badges = [];
    if (data.isProtected) badges.push('<span class="detail-badge badge-anchor">ANCHORED</span>');
    if (data.storeType) badges.push('<span class="detail-badge badge-store">' + data.storeType.toUpperCase() + '</span>');
    if (data.entityType) badges.push('<span class="detail-badge badge-entity">' + data.entityType.toUpperCase() + '</span>');
    if (data.emotion && data.emotion !== 'neutral') badges.push('<span class="detail-badge" style="color:' + (emoColors[data.emotion] || '#90a4ae') + ';border-color:' + (emoColors[data.emotion] || '#90a4ae') + '40">' + data.emotion.toUpperCase() + '</span>');
    if (badges.length) {
      h += '<div style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">' + badges.join('') + '</div>';
    }

    content.innerHTML = h;
    panel.classList.add('open');

    // Wire up connection item clicks → navigate to that node
    var connItems = content.querySelectorAll('.conn-item[data-node-id]');
    connItems.forEach(function(el) {
      el.addEventListener('click', function() {
        var targetId = el.dataset.nodeId;
        if (targetId) selectNodeById(targetId);
      });
    });
  }

  function closeDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (panel) panel.classList.remove('open');
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Close button
  document.addEventListener('DOMContentLoaded', function() {
    var closeBtn = document.getElementById('close-detail');
    if (closeBtn) closeBtn.addEventListener('click', deselectNode);
  });

  // Escape key
  window.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') deselectNode();
  });

  // Export
  JUG.selectNodeById = selectNodeById;
  JUG.deselectNode = deselectNode;
})();
