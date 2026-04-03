// Cortex Neural Graph — Entity Detail Panel
// Fetches and renders entity profiles when an entity node is selected.
// Hooks into graph:selectNode — only activates for entity-type nodes.
(function() {

  var API_BASE = '';

  function isEntityNode(node) {
    return node && node.type === 'entity';
  }

  function fetchEntityDetail(entityId, callback) {
    var url = API_BASE + '/api/entity?entity_id=' + encodeURIComponent(entityId);
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) { callback(null, data); })
      .catch(function(err) { callback(err, null); });
  }

  // ── Heat gauge ──

  function buildHeatGauge(heat) {
    var pct = Math.round((heat || 0) * 100);
    var color = pct >= 70 ? '#40D870' : pct >= 40 ? '#E0B040' : '#E07070';
    var h = '<div class="gauge-header">';
    h += '<span class="gauge-label">Heat</span>';
    h += '<span class="gauge-val" style="color:' + color + '">' + pct + '%</span>';
    h += '</div>';
    h += '<div class="gauge-track"><div class="gauge-fill" style="width:' +
      pct + '%;background:' + color + '"></div></div>';
    return h;
  }

  // ── Stats section ──

  function buildStats(profile) {
    var stats = profile.stats || {};
    var h = '<div class="section-title">Statistics</div>';
    h += '<div class="entity-stats">';
    h += '<div class="entity-stat"><span class="entity-stat-num">' +
      (stats.total_mentions || 0) + '</span><span class="entity-stat-label">Mentions</span></div>';
    h += '<div class="entity-stat"><span class="entity-stat-num">' +
      (stats.episodic_count || 0) + '</span><span class="entity-stat-label">Episodic</span></div>';
    h += '<div class="entity-stat"><span class="entity-stat-num">' +
      (stats.semantic_count || 0) + '</span><span class="entity-stat-label">Semantic</span></div>';
    h += '<div class="entity-stat"><span class="entity-stat-num">' +
      (stats.avg_heat !== undefined ? stats.avg_heat.toFixed(2) : '--') +
      '</span><span class="entity-stat-label">Avg Heat</span></div>';
    h += '</div>';
    return h;
  }

  // ── Temporal span ──

  function buildTemporal(span) {
    if (!span || (!span.first_seen && !span.last_seen)) return '';
    var fmt = function(d) {
      if (!d) return '--';
      try { return new Date(d).toLocaleDateString(); }
      catch(e) { return d.substring(0, 10); }
    };
    var h = '<div class="section-title">Temporal Span</div>';
    h += '<div class="entity-temporal">';
    h += '<span class="entity-temporal-date">' + fmt(span.first_seen) + '</span>';
    h += '<span class="entity-temporal-arrow">&#x2192;</span>';
    h += '<span class="entity-temporal-date">' + fmt(span.last_seen) + '</span>';
    h += '</div>';
    return h;
  }

  // ── Domains ──

  function buildDomains(domains) {
    if (!domains || !domains.length) return '';
    var h = '<div class="section-title">Domains</div><div class="tag-row">';
    domains.forEach(function(d) {
      h += '<span class="tag">' + JUG._fmt.esc(d) + '</span>';
    });
    h += '</div>';
    return h;
  }

  // ── Top memories list ──

  function buildTopMemories(memories) {
    if (!memories || !memories.length) return '';
    var h = '<div class="section-title">Top Memories (' + memories.length + ')</div>';
    memories.forEach(function(m) {
      var heatPct = Math.round((m.heat || 0) * 100);
      var color = heatPct >= 70 ? '#40D870' : heatPct >= 40 ? '#E0B040' : '#E07070';
      h += '<div class="entity-memory-item" data-memory-id="' + m.id + '">';
      h += '<div class="entity-memory-heat" style="color:' + color + '">' + heatPct + '%</div>';
      h += '<div class="entity-memory-text">' + JUG._fmt.esc(m.content_preview || '') + '</div>';
      h += '</div>';
    });
    return h;
  }

  // ── Related entities list ──

  function buildRelatedEntities(related) {
    if (!related || !related.length) return '';
    var h = '<div class="section-title">Related Entities (' + related.length + ')</div>';
    h += '<div class="related-entities">';
    related.forEach(function(r) {
      var relLabel = (r.relationship_type || 'related').replace(/_/g, ' ');
      h += '<div class="related-entity-item" data-entity-id="' + r.entity_id + '">';
      h += '<span class="related-entity-name">' + JUG._fmt.esc(r.name || 'Entity #' + r.entity_id) + '</span>';
      h += '<span class="related-entity-type">' + JUG._fmt.esc(relLabel) + '</span>';
      h += '</div>';
    });
    h += '</div>';
    return h;
  }

  // ── Main render ──

  function renderEntityProfile(profile) {
    var col = '#50C8E0';
    var h = '<div class="entity-profile">';
    h += '<div class="node-badge" style="background:' + col +
      '10;border-color:' + col + '40;color:' + col + '">';
    h += '<span style="width:5px;height:5px;border-radius:50%;background:' +
      col + ';display:inline-block;box-shadow:0 0 6px ' + col + '"></span> ' +
      JUG._fmt.esc(profile.type || 'Entity') + '</div>';
    h += '<h2>' + JUG._fmt.esc(profile.name) + '</h2>';
    if (profile.domain) {
      h += '<div class="domain-label">' + JUG._fmt.esc(profile.domain) + '</div>';
    }
    h += '<div class="gauge-grid">' + buildHeatGauge(profile.heat) + '</div>';
    h += buildStats(profile);
    h += buildDomains(profile.domains);
    h += buildTemporal(profile.temporal_span);
    h += buildTopMemories(profile.top_memories);
    h += buildRelatedEntities(profile.related_entities);
    h += '</div>';
    return h;
  }

  // ── Wire interactions ──

  function wireEntityInteractions(content) {
    content.querySelectorAll('.entity-memory-item[data-memory-id]').forEach(function(el) {
      el.addEventListener('click', function() {
        var memId = 'memory-' + el.dataset.memoryId;
        JUG.selectNodeById(memId);
      });
    });
    content.querySelectorAll('.related-entity-item[data-entity-id]').forEach(function(el) {
      el.addEventListener('click', function() {
        var entId = 'entity-' + el.dataset.entityId;
        var node = null;
        var gd = JUG.getGraph ? JUG.getGraph().graphData() : { nodes: [] };
        for (var i = 0; i < gd.nodes.length; i++) {
          if (gd.nodes[i].id === entId) { node = gd.nodes[i]; break; }
        }
        if (node) {
          JUG.selectNodeById(entId);
        } else {
          // Fetch and show the entity directly
          var eid = el.dataset.entityId;
          fetchEntityDetail(eid, function(err, data) {
            if (!err && data && data.entity) {
              showEntityPanel(data.entity);
            }
          });
        }
      });
    });
  }

  function showEntityPanel(profile) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    if (!panel || !content) return;
    content.innerHTML = renderEntityProfile(profile);
    panel.classList.add('open');
    wireEntityInteractions(content);
  }

  // ── Hook into graph:selectNode ──

  JUG.on('graph:selectNode', function(node) {
    if (!isEntityNode(node)) return;

    var rawId = node.id || '';
    var entityId = rawId.replace(/^entity-/, '');
    if (!entityId || isNaN(parseInt(entityId))) return;

    fetchEntityDetail(entityId, function(err, data) {
      if (err || !data || !data.entity) return;
      showEntityPanel(data.entity);
    });
  });

})();
