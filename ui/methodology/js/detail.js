// Cortex Methodology Map — Detail Panel
window.CMV = window.CMV || {};

/**
 * Open the detail panel for a given node, rendering metrics and blind spots.
 * @param {Object} node - Graph node object.
 */
CMV.openDetail = function (node) {
  var col = CMV.COLORS[node.type] || '#00FFFF';
  var h = '<div class="node-badge" style="background:' + col + '10;border-color:' + col + '40;color:' + col + '">'
    + '<span style="width:5px;height:5px;border-radius:50%;background:' + col + ';display:inline-block;box-shadow:0 0 6px ' + col + '"></span>'
    + (CMV.LABELS[node.type] || node.type)
    + '</div>'
    + '<h2>' + node.label + '</h2>'
    + '<div class="domain-label">' + (node.domain || '') + '</div>';

  var m = [];
  if (node.sessionCount != null) m.push(['Sessions', node.sessionCount, '']);
  if (node.frequency != null)    m.push(['Freq', node.frequency, 'x']);
  if (node.confidence != null && !node._bs) m.push(['Conf', Math.round(node.confidence * 100), '%']);
  if (node.ratio != null)        m.push(['Usage', Math.round(node.ratio * 100), '%']);
  if (node.avgPerSession != null) m.push(['Avg/Sess', node.avgPerSession, '']);

  if (m.length) {
    h += '<div class="section-title">Metrics</div><div class="metric-grid">'
      + m.map(function (item) {
        return '<div class="metric-card"><div class="metric-label">' + item[0]
          + '</div><div class="metric-val">' + item[1]
          + '<span class="metric-unit">' + item[2] + '</span></div></div>';
      }).join('')
      + '</div>';
  }

  if (node.confidence != null && !node._bs) {
    var pct = Math.round(node.confidence * 100);
    h += '<div style="display:flex;justify-content:space-between;font-size:7px;color:var(--text-dim);letter-spacing:1px;text-transform:uppercase">'
      + '<span>Confidence</span><span style="color:' + col + ';font-family:Orbitron">' + pct + '%</span></div>'
      + '<div class="conf-bar-bg"><div class="conf-bar-fill" style="width:' + pct + '%;background:' + col + ';box-shadow:0 0 8px ' + col + '40"></div></div>';
  }

  if (node._bs) {
    h += '<div class="section-title">Analysis</div>'
      + '<div class="bs-card"><div class="bs-sev ' + node.severity + '">' + node.severity + '</div>'
      + '<div class="bs-desc">' + node.description + '</div>'
      + '<div class="bs-sug">' + node.suggestion + '</div></div>';
  }

  if (node.type === 'domain' && CMV.graphData) {
    var dbs = CMV.graphData.blindSpotRegions
      .filter(function (b) { return b.domain === node.domain; })
      .slice(0, 5);
    if (dbs.length) {
      h += '<div class="section-title">Blind Spots (' + dbs.length + ')</div>'
        + dbs.map(function (b) {
          return '<div class="bs-card"><div class="bs-sev ' + b.severity + '">' + b.severity + '</div>'
            + '<div class="bs-desc">' + b.description + '</div>'
            + '<div class="bs-sug">' + b.suggestion + '</div></div>';
        }).join('');
    }
  }

  document.getElementById('detail-content').innerHTML = h;
  document.getElementById('detail-panel').classList.add('open');
};

/**
 * Close the detail panel and reset focus state.
 */
CMV.closeDetail = function () {
  document.getElementById('detail-panel').classList.remove('open');
  CMV.selectedId = null;
  CMV.focused = false;
  if (CMV.graph) CMV.graph.nodeOpacity(function () { return 1; });
};

/**
 * Get all node IDs connected to the given node (including itself).
 * @param {string} id - Node ID.
 * @returns {Set<string>} Connected node IDs.
 */
CMV.getConnected = function (id) {
  var s = new Set([id]);
  CMV.graphData.edges.forEach(function (e) {
    var a = typeof e.source === 'object' ? e.source.id : e.source;
    var b = typeof e.target === 'object' ? e.target.id : e.target;
    if (a === id) s.add(b);
    if (b === id) s.add(a);
  });
  return s;
};
