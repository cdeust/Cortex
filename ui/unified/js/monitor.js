// Cortex Neural Graph — Monitoring Log
(function() {
  var logEntries = [];
  var activeTypeFilter = 'all';
  var activeBioFilter = '';
  var maxEntries = 2000;
  var panel = null;
  var logBody = null;
  var visible = false;

  function init() {
    panel = document.getElementById('monitor-panel');
    logBody = document.getElementById('monitor-log');
    if (!panel || !logBody) return;

    var toggleBtn = document.getElementById('monitor-toggle');
    if (toggleBtn) toggleBtn.addEventListener('click', toggle);

    var closeBtn = document.getElementById('monitor-close');
    if (closeBtn) closeBtn.addEventListener('click', hide);

    // Type tabs
    var typeTabs = panel.querySelectorAll('.mon-tab[data-type]');
    typeTabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        typeTabs.forEach(function(t) { t.classList.remove('active'); });
        tab.classList.add('active');
        activeTypeFilter = tab.dataset.type || 'all';
        // Clear bio filter when switching type
        activeBioFilter = '';
        panel.querySelectorAll('.mon-tab[data-bio]').forEach(function(t) { t.classList.remove('active'); });
        renderLog();
      });
    });

    // Bio tabs
    var bioTabs = panel.querySelectorAll('.mon-tab[data-bio]');
    bioTabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        var wasActive = tab.classList.contains('active');
        bioTabs.forEach(function(t) { t.classList.remove('active'); });
        if (!wasActive) {
          tab.classList.add('active');
          activeBioFilter = tab.dataset.bio || '';
        } else {
          activeBioFilter = '';
        }
        renderLog();
      });
    });

    // Click delegation for log entries
    logBody.addEventListener('click', function(e) {
      var entry = e.target.closest('.mon-entry');
      if (!entry) return;

      var nodeId = entry.dataset.nodeId;

      // Toggle expand
      var wasExpanded = entry.classList.contains('expanded');
      // Collapse all
      logBody.querySelectorAll('.mon-entry.expanded').forEach(function(el) {
        el.classList.remove('expanded');
      });

      if (!wasExpanded) {
        entry.classList.add('expanded');
      }

      // Navigate to node in graph on click
      if (nodeId && JUG.selectNodeById) {
        JUG.selectNodeById(nodeId);
      }
    });

    window.addEventListener('keydown', function(e) {
      if (e.target.tagName === 'INPUT') return;
      if (e.key === 'm' || e.key === 'M') toggle();
    });
  }

  function toggle() { visible ? hide() : show(); }
  function show() { visible = true; if (panel) panel.classList.add('open'); renderLog(); }
  function hide() { visible = false; if (panel) panel.classList.remove('open'); }

  function logNodes(nodes) {
    if (!nodes || !nodes.length) return;

    // Compute connection info from live graph
    var edgeMap = JUG.edgeNodeMap || {};
    var edges = JUG.getActiveEdges ? JUG.getActiveEdges() : [];
    var allNodes = JUG.allNodes || [];

    nodes.forEach(function(n) {
      // Find this node's index in allNodes for connection lookup
      var nodeIdx = -1;
      for (var ni = allNodes.length - 1; ni >= 0; ni--) {
        if (allNodes[ni].data.id === n.id) { nodeIdx = ni; break; }
      }

      var connections = [];
      if (nodeIdx >= 0 && edgeMap[nodeIdx]) {
        edgeMap[nodeIdx].forEach(function(ei) {
          var e = edges[ei];
          if (!e) return;
          var otherIdx = e.srcIdx === nodeIdx ? e.tgtIdx : e.srcIdx;
          var other = allNodes[otherIdx];
          if (other) {
            connections.push({
              label: other.data.label || other.data.id,
              type: e.type,
              nodeType: other.data.type,
              color: JUG.getNodeColor(other.data),
              weight: e.weight,
              id: other.data.id,
            });
          }
        });
      }

      logEntries.push({
        time: new Date(),
        type: n.type || 'unknown',
        id: n.id || '',
        label: n.label || '',
        domain: n.domain || '',
        group: n.group || '',
        color: n.color || '#00FFFF',
        heat: n.heat,
        importance: n.importance,
        confidence: n.confidence,
        frequency: n.frequency,
        ratio: n.ratio,
        content: n.content || n.label || '',
        entityType: n.entityType || '',
        storeType: n.storeType || '',
        tags: n.tags || [],
        isProtected: n.isProtected || false,
        accessCount: n.accessCount || 0,
        activation: n.activation,
        sessionCount: n.sessionCount,
        avgPerSession: n.avgPerSession,
        size: n.size,
        emotion: n.emotion || '',
        arousal: n.arousal,
        emotionalBoost: n.emotionalBoost,
        decayResistance: n.decayResistance,
        valence: n.valence,
        connections: connections,
      });
    });

    if (logEntries.length > maxEntries) {
      logEntries = logEntries.slice(logEntries.length - maxEntries);
    }

    updateBadge();
    if (visible) renderLog();
  }

  function updateBadge() {
    var badge = document.getElementById('monitor-badge');
    if (badge) badge.textContent = logEntries.length;
  }

  function renderLog() {
    if (!logBody) return;

    // Apply type filter
    var filtered = activeTypeFilter === 'all'
      ? logEntries
      : logEntries.filter(function(e) { return e.type === activeTypeFilter; });

    // Apply bio filter on top
    if (activeBioFilter) {
      filtered = filtered.filter(function(e) {
        if (activeBioFilter === 'emotional') return e.emotion && e.emotion !== 'neutral' && e.emotion !== '';
        if (activeBioFilter === 'protected') return e.isProtected;
        if (activeBioFilter === 'high-heat') return (e.heat || 0) >= 0.7;
        // Specific emotion
        return e.emotion === activeBioFilter;
      });
    }

    // Tab counts (type)
    var counts = {};
    logEntries.forEach(function(e) { counts[e.type] = (counts[e.type] || 0) + 1; });
    (panel || document).querySelectorAll('.mon-tab[data-type]').forEach(function(tab) {
      var t = tab.dataset.type;
      var countEl = tab.querySelector('.mon-count');
      if (countEl) countEl.textContent = t === 'all' ? logEntries.length : (counts[t] || 0);
    });

    // Tab counts (bio)
    var bioCounts = { emotional: 0, urgency: 0, frustration: 0, satisfaction: 0, discovery: 0, confusion: 0, protected: 0, 'high-heat': 0 };
    logEntries.forEach(function(e) {
      if (e.emotion && e.emotion !== 'neutral' && e.emotion !== '') {
        bioCounts.emotional++;
        if (bioCounts[e.emotion] !== undefined) bioCounts[e.emotion]++;
      }
      if (e.isProtected) bioCounts.protected++;
      if ((e.heat || 0) >= 0.7) bioCounts['high-heat']++;
    });
    (panel || document).querySelectorAll('.mon-tab[data-bio]').forEach(function(tab) {
      var b = tab.dataset.bio;
      var countEl = tab.querySelector('.mon-count');
      if (countEl) countEl.textContent = bioCounts[b] || 0;
    });

    var html = '';
    for (var i = filtered.length - 1; i >= Math.max(0, filtered.length - 500); i--) {
      var e = filtered[i];
      var time = e.time.toLocaleTimeString('en-US', { hour12: false });
      var typeLabel = JUG.NODE_LABELS[e.type] || e.type;
      var color = e.color;
      var connCount = e.connections ? e.connections.length : 0;

      html += '<div class="mon-entry" data-node-id="' + e.id + '">';

      // ── Header row ──
      html += '<div class="mon-entry-header">';
      html += '<span class="mon-time">' + time + '</span>';
      html += '<span class="mon-type" style="color:' + color + '">' + typeLabel + '</span>';
      if (e.entityType) html += '<span class="mon-subtype">' + e.entityType + '</span>';
      if (e.storeType) html += '<span class="mon-subtype">' + e.storeType + '</span>';
      if (e.isProtected) html += '<span class="mon-subtype mon-anchored">ANCHORED</span>';
      if (e.emotion && e.emotion !== 'neutral') {
        var emoColors = { urgency: '#ff3366', frustration: '#ef4444', satisfaction: '#22c55e', discovery: '#f59e0b', confusion: '#8b5cf6' };
        html += '<span class="mon-subtype" style="color:' + (emoColors[e.emotion] || '#90a4ae') + ';border-color:' + (emoColors[e.emotion] || '#90a4ae') + '40">' + e.emotion + '</span>';
      }
      if (connCount > 0) html += '<span class="mon-conn-badge">' + connCount + ' conn</span>';
      html += '<span class="mon-id">' + e.id + '</span>';
      if (e.domain) html += '<span class="mon-domain">' + e.domain + '</span>';
      html += '</div>';

      // ── Content (always visible, truncated unless expanded) ──
      html += '<div class="mon-content">' + escapeHtml(e.content || e.label) + '</div>';

      // ── Metrics bar ──
      var metrics = [];
      if (e.heat !== undefined && e.heat !== null) metrics.push('<span class="mon-m">heat <b>' + e.heat + '</b></span>');
      if (e.importance !== undefined && e.importance !== null) metrics.push('<span class="mon-m">imp <b>' + e.importance + '</b></span>');
      if (e.confidence !== undefined && e.confidence !== null) metrics.push('<span class="mon-m">conf <b>' + (e.confidence * 100).toFixed(0) + '%</b></span>');
      if (e.frequency !== undefined && e.frequency !== null) metrics.push('<span class="mon-m">freq <b>' + e.frequency + '</b></span>');
      if (e.ratio !== undefined && e.ratio !== null) metrics.push('<span class="mon-m">usage <b>' + (e.ratio * 100).toFixed(0) + '%</b></span>');
      if (e.activation !== undefined && e.activation !== null) metrics.push('<span class="mon-m">act <b>' + e.activation.toFixed(3) + '</b></span>');
      if (e.sessionCount !== undefined && e.sessionCount !== null) metrics.push('<span class="mon-m">sessions <b>' + e.sessionCount + '</b></span>');
      if (e.avgPerSession !== undefined && e.avgPerSession !== null) metrics.push('<span class="mon-m">avg/sess <b>' + e.avgPerSession + '</b></span>');
      if (e.accessCount) metrics.push('<span class="mon-m">access <b>' + e.accessCount + '</b></span>');
      if (e.size !== undefined) metrics.push('<span class="mon-m">size <b>' + e.size.toFixed(1) + '</b></span>');
      if (e.arousal !== undefined && e.arousal > 0.1) metrics.push('<span class="mon-m">arousal <b>' + (e.arousal * 100).toFixed(0) + '%</b></span>');
      if (e.emotionalBoost !== undefined && e.emotionalBoost > 1.01) metrics.push('<span class="mon-m">emo×<b>' + e.emotionalBoost.toFixed(2) + '</b></span>');
      if (e.decayResistance !== undefined && e.decayResistance > 1.01) metrics.push('<span class="mon-m">resist <b>' + e.decayResistance.toFixed(2) + '</b></span>');

      if (metrics.length) {
        html += '<div class="mon-metrics">' + metrics.join('') + '</div>';
      }

      // ── Tags ──
      if (e.tags && e.tags.length) {
        html += '<div class="mon-tags">' + e.tags.map(function(t) {
          return '<span class="mon-tag">' + escapeHtml(t) + '</span>';
        }).join('') + '</div>';
      }

      // ── Expandable: connections (shown on click) ──
      if (connCount > 0) {
        html += '<div class="mon-expand">';
        html += '<div class="mon-expand-title">Connections</div>';
        e.connections.forEach(function(c) {
          html += '<div class="mon-conn-item" data-node-id="' + c.id + '">';
          html += '<span class="mon-conn-dot" style="background:' + c.color + '"></span>';
          html += '<span class="mon-conn-edge-type">' + (c.type || '').replace(/_/g, ' ') + '</span>';
          html += '<span class="mon-conn-name">' + escapeHtml(c.label) + '</span>';
          html += '<span class="mon-conn-weight">' + (c.weight || 0).toFixed(2) + '</span>';
          html += '</div>';
        });
        html += '</div>';
      }

      html += '</div>';
    }

    logBody.innerHTML = html;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    requestAnimationFrame(init);
  }

  JUG.logNodes = logNodes;
  JUG.toggleMonitor = toggle;
})();
