// Cortex Memory Dashboard — Timeline
(function() {
  var CMD = window.CMD;

  CMD.buildTimelineTable = function() {
    var timelineTableEl = document.getElementById('timeline-table');
    var items = [];
    CMD.nodes.filter(function(n) { return n._vis !== false; }).forEach(function(n) {
      var kind, kindClass;
      if (n.id && n.id.startsWith('e_')) {
        kind = 'Entity'; kindClass = 'entity';
      } else if (n.store_type === 'episodic') {
        kind = 'Episodic'; kindClass = 'episodic';
      } else if (n.store_type === 'semantic') {
        kind = 'Semantic'; kindClass = 'semantic';
      } else {
        kind = 'Memory'; kindClass = 'episodic';
      }
      items.push({
        kind: kind, kindClass: kindClass,
        name: n.name || '(unnamed)',
        domain: CMD.cleanProject(n.project),
        heat: (n.heat || 0).toFixed(2),
        importance: n.importance !== undefined ? (n.importance).toFixed(2) : '\u2014',
        tags: n.tags || [],
        created: n.created_at || '',
        connections: n.connections || 0,
        stage: n.consolidation_stage || '\u2014',
        hippo_dep: n.hippocampal_dependency !== undefined ? (n.hippocampal_dependency).toFixed(2) : '\u2014',
      });
    });

    items.sort(function(a, b) {
      var order = { entity: 0, semantic: 1, episodic: 2 };
      var oa = order[a.kindClass] !== undefined ? order[a.kindClass] : 3;
      var ob = order[b.kindClass] !== undefined ? order[b.kindClass] : 3;
      if (oa !== ob) return oa - ob;
      return parseFloat(b.heat) - parseFloat(a.heat);
    });

    var escHtml = CMD.escHtml;
    var html = '<table><thead><tr>';
    html += '<th>Type</th><th>Name</th><th>Domain</th><th>Heat</th><th>Imp</th><th>Stage</th><th>H\u2192C</th><th>Tags</th>';
    html += '</tr></thead><tbody>';
    items.forEach(function(it) {
      html += '<tr>';
      html += '<td><span class="tl-dot tl-dot-' + it.kindClass + '"></span><span class="tl-type tl-type-' + it.kindClass + '">' + escHtml(it.kind) + '</span></td>';
      html += '<td class="tl-name">' + escHtml(it.name) + '</td>';
      html += '<td class="tl-domain">' + escHtml(it.domain) + '</td>';
      html += '<td class="tl-heat">' + it.heat + '</td>';
      html += '<td class="tl-heat">' + it.importance + '</td>';
      html += '<td style="font-size:7px;color:' + (CMD.STAGE_COLORS[it.stage] || '#666') + '">' + escHtml(it.stage) + '</td>';
      html += '<td class="tl-heat">' + it.hippo_dep + '</td>';
      html += '<td class="tl-tags">' + (it.tags.length ? it.tags.map(function(t) { return '<span>' + escHtml(t) + '</span>'; }).join('') : '<span style="color:rgba(255,255,255,0.12)">\u2014</span>') + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    timelineTableEl.innerHTML = html;
  };

  CMD.showTimelineView = function() {
    document.getElementById('timeline-table').style.display = 'block';
    CMD.renderer.domElement.style.display = 'none';
    document.getElementById('legend-brain').style.display = 'none';
    document.getElementById('hint').style.display = 'none';
    document.getElementById('hud').style.display = 'none';
    CMD.buildTimelineTable();
  };

  CMD.showBrainView = function() {
    document.getElementById('timeline-table').style.display = 'none';
    CMD.renderer.domElement.style.display = 'block';
    document.getElementById('legend-brain').style.display = '';
    document.getElementById('hint').style.display = '';
    document.getElementById('hud').style.display = '';
  };
})();
