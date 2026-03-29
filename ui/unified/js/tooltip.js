// Cortex Neural Graph — Rich Tooltip Card
// Shows type badge, heat gauge, key metric, content preview, quality dot
// For file entities: async-loads git diff preview
(function() {
  var tip = null;
  var moveHandler = null;
  var diffCache = {};
  var activeNodeId = null;

  // Metric lookup: which single metric matters most per node type
  var METRIC_KEY = {
    'domain':              { field: 'sessionCount', label: 'Sessions',   fmt: fmtInt },
    'entry-point':         { field: 'frequency',    label: 'Frequency',  fmt: fmtInt },
    'recurring-pattern':   { field: 'frequency',    label: 'Frequency',  fmt: fmtInt },
    'tool-preference':     { field: 'ratio',        label: 'Usage',      fmt: fmtPct },
    'behavioral-feature':  { field: 'activation',   label: 'Activation', fmt: fmtDec },
    'memory':              { field: 'importance',    label: 'Importance', fmt: fmtDec },
    'entity':              { field: 'confidence',    label: 'Confidence', fmt: fmtPct },
  };

  function fmtInt(v) { return v != null ? String(Math.round(v)) : '--'; }
  function fmtPct(v) { return v != null ? Math.round(v * 100) + '%' : '--'; }
  function fmtDec(v) { return v != null ? v.toFixed(2) : '--'; }

  // ── Card builder ──

  function buildBadge(node) {
    var color = JUG.getNodeColor(node);
    var label = resolveTypeLabel(node);
    return '<div class="tt-badge" style="border-color:' + color + '40">' +
      '<span class="tt-badge-dot" style="background:' + color +
      ';box-shadow:0 0 6px ' + color + '60"></span>' +
      '<span style="color:' + color + '">' + label + '</span></div>';
  }

  function resolveTypeLabel(node) {
    if (node.type === 'entity' && node.entityType) {
      return node.entityType.charAt(0).toUpperCase() + node.entityType.slice(1);
    }
    return JUG.NODE_LABELS[node.type] || node.type;
  }

  function buildHeatGauge(node) {
    if (node.heat === undefined && node.heat !== 0) return '';
    var pct = Math.max(0, Math.min(100, (node.heat || 0) * 100));
    var barColor = pct > 60 ? '#E05050' : pct > 30 ? '#E0B040' : '#50A0C0';
    return '<div class="tt-heat">' +
      '<span class="tt-heat-label">HEAT</span>' +
      '<div class="tt-heat-track">' +
      '<div class="tt-heat-fill" style="width:' + pct +
      '%;background:' + barColor + '"></div></div>' +
      '<span class="tt-heat-val">' + (node.heat || 0).toFixed(2) + '</span></div>';
  }

  function buildKeyMetric(node) {
    var spec = METRIC_KEY[node.type];
    if (!spec) return '';
    var val = node[spec.field];
    if (val === undefined) return '';
    return '<div class="tt-kv"><span class="tt-kv-label">' +
      spec.label + '</span><span class="tt-kv-val">' +
      spec.fmt(val) + '</span></div>';
  }

  function buildQualityDot(node) {
    if (node.quality === undefined) return '';
    var q = node.quality;
    var color = q >= 0.6 ? '#40D870' : q >= 0.3 ? '#E0B040' : '#E05050';
    var label = q >= 0.6 ? 'Strong' : q >= 0.3 ? 'Moderate' : 'Weak';
    return '<div class="tt-kv"><span class="tt-kv-label">Quality</span>' +
      '<span class="tt-kv-val" style="color:' + color + '">' +
      Math.round(q * 100) + '% ' + label + '</span></div>';
  }

  function buildPreview(node) {
    var text = node.content || node.label || '';
    if (!text || text === node.label) return '';
    var preview = text.length > 80 ? text.substring(0, 77) + '...' : text;
    return '<div class="tt-preview">' + escapeHtml(preview) + '</div>';
  }

  function buildEmotionTag(node) {
    if (!node.emotion || node.emotion === 'neutral') return '';
    var colors = {
      urgency: '#ff3366', frustration: '#ef4444',
      satisfaction: '#22c55e', discovery: '#f59e0b', confusion: '#8b5cf6',
    };
    var c = colors[node.emotion] || '#d946ef';
    return '<div class="tt-emotion" style="color:' + c + '">' +
      node.emotion.charAt(0).toUpperCase() + node.emotion.slice(1) + '</div>';
  }

  function buildCard(node) {
    var parts = [buildBadge(node)];
    var label = (JUG._fmt && JUG._fmt.cleanLabel) ? JUG._fmt.cleanLabel(node.label || '') : (node.label || '');
    parts.push('<div class="tt-label">' + escapeHtml(label) + '</div>');
    if (node.domain) {
      parts.push('<div class="tt-domain">' + escapeHtml(node.domain) + '</div>');
    }
    parts.push(buildHeatGauge(node));
    parts.push(buildKeyMetric(node));
    parts.push(buildQualityDot(node));
    parts.push(buildEmotionTag(node));
    parts.push(buildPreview(node));
    // Diff placeholder for file entities — filled async
    if (isFileEntity(node)) {
      parts.push('<div class="tt-diff" id="tt-diff-slot">loading diff...</div>');
    }
    return parts.join('');
  }

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── File diff ──

  function isFileEntity(node) {
    return node.type === 'entity' && node.entityType === 'file';
  }

  function fetchDiff(node) {
    var name = node.label || node.content || '';
    if (!name) return;
    var cacheKey = name;
    if (diffCache[cacheKey]) {
      renderDiff(diffCache[cacheKey], node.id);
      return;
    }
    var url = '/api/file-diff?name=' + encodeURIComponent(name);
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
      diffCache[cacheKey] = data;
      renderDiff(data, node.id);
    }).catch(function() {
      renderDiff({ diff_type: 'none', lines: [] }, node.id);
    });
  }

  function renderDiff(data, nodeId) {
    // Only render if we're still hovering the same node
    if (activeNodeId !== nodeId) return;
    var slot = document.getElementById('tt-diff-slot');
    if (!slot) return;
    if (data.diff_type === 'none' || !data.lines || !data.lines.length) {
      slot.innerHTML = '<span class="tt-diff-empty">no changes</span>';
      return;
    }
    var label = data.diff_type === 'uncommitted' ? 'Working changes' : 'Last commit';
    var html = '<div class="tt-diff-header">' + label + '</div>';
    html += '<div class="tt-diff-lines">';
    for (var i = 0; i < data.lines.length; i++) {
      var ln = data.lines[i];
      html += '<div class="tt-diff-' + ln.type + '">' +
        escapeHtml(ln.text) + '</div>';
    }
    if (data.truncated) {
      html += '<div class="tt-diff-truncated">... truncated</div>';
    }
    html += '</div>';
    slot.innerHTML = html;
  }

  // ── Show / Hide ──

  function show(node) {
    if (!tip) tip = document.getElementById('tooltip');
    if (!tip) return;
    activeNodeId = node.id;
    tip.innerHTML = buildCard(node);
    tip.classList.add('visible');
    moveHandler = function(e) { positionTooltip(e.clientX, e.clientY); };
    window.addEventListener('mousemove', moveHandler);
    if (isFileEntity(node)) fetchDiff(node);
  }

  function positionTooltip(cx, cy) {
    var tx = cx + 16, ty = cy + 16;
    if (tx + 300 > innerWidth) tx = cx - 316;
    if (ty + 200 > innerHeight) ty = cy - 216;
    tip.style.left = tx + 'px';
    tip.style.top = ty + 'px';
  }

  function hide() {
    if (!tip) tip = document.getElementById('tooltip');
    if (!tip) return;
    activeNodeId = null;
    tip.classList.remove('visible');
    if (moveHandler) {
      window.removeEventListener('mousemove', moveHandler);
      moveHandler = null;
    }
  }

  // ── Export ──
  JUG._tooltip = { show: show, hide: hide };
})();
