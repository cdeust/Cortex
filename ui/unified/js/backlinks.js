// Cortex Neural Graph — Backlinks Panel
// Renders entity backlinks inside the detail panel when a memory is selected.
// Fetches /api/backlinks for each entity of the selected memory.
(function() {

  function fetchBacklinks(entityId) {
    return fetch('/api/backlinks?entity_id=' + entityId + '&limit=20')
      .then(function(r) { return r.json(); })
      .catch(function() { return { total: 0, by_domain: {}, top: [] }; });
  }

  function renderBacklinksSection(allResults) {
    if (!allResults.length) return '';
    var total = 0;
    var items = [];

    allResults.forEach(function(result) {
      if (!result || !result.top) return;
      total += result.total;
      result.top.forEach(function(bl) {
        if (!items.some(function(x) { return x.memory_id === bl.memory_id; })) {
          items.push(bl);
        }
      });
    });

    if (!items.length) return '';

    items.sort(function(a, b) { return b.relevance - a.relevance; });
    var shown = items.slice(0, 15);

    var h = '<div class="section-title">Backlinks (' + total + ')</div>';
    h += '<div class="backlinks-list">';

    // Group by domain
    var byDomain = {};
    shown.forEach(function(bl) {
      var d = bl.domain || 'unknown';
      if (!byDomain[d]) byDomain[d] = [];
      byDomain[d].push(bl);
    });

    var domains = Object.keys(byDomain).sort();
    domains.forEach(function(domain) {
      h += '<div class="backlink-domain">';
      h += '<div class="backlink-domain-label">' + esc(domain) + '</div>';
      byDomain[domain].forEach(function(bl) {
        var heat = bl.heat || 0;
        var heatBar = Math.round(Math.min(heat, 1) * 100);
        h += '<div class="backlink-item" data-memory-id="' + bl.memory_id + '">';
        h += '<div class="backlink-snippet">' + esc(bl.snippet) + '</div>';
        h += '<div class="backlink-meta">';
        h += '<span class="backlink-type">' + esc(bl.store_type) + '</span>';
        h += '<span class="backlink-heat">';
        h += '<span class="bio-bar" style="width:40px;display:inline-block;vertical-align:middle">';
        h += '<span class="bio-fill" style="width:' + heatBar + '%;background:#E8B840"></span>';
        h += '</span> ' + heat.toFixed(2);
        h += '</span>';
        if (bl.is_protected) h += '<span class="backlink-badge">protected</span>';
        h += '</div></div>';
      });
      h += '</div>';
    });

    h += '</div>';
    return h;
  }

  function wireBacklinkClicks(container) {
    container.querySelectorAll('.backlink-item[data-memory-id]').forEach(function(el) {
      el.addEventListener('click', function() {
        var memId = parseInt(el.dataset.memoryId, 10);
        var nodeId = 'mem-' + memId;
        // Try standard memory node ID formats
        if (JUG.selectNodeById) {
          JUG.selectNodeById(nodeId);
        }
        JUG.emit('localgraph:navigate', { memory_id: memId });
      });
    });
  }

  function loadAndRender(node) {
    if (node.type !== 'memory' || !node.memoryId) return;

    var localGraphData = JUG._localGraphData;
    if (!localGraphData || !localGraphData.nodes) return;

    var entities = localGraphData.nodes.filter(function(n) {
      return n.type === 'entity' && n.entity_id;
    });
    if (!entities.length) return;

    var promises = entities.map(function(ent) {
      return fetchBacklinks(ent.entity_id);
    });

    Promise.all(promises).then(function(results) {
      var html = renderBacklinksSection(results);
      if (!html) return;
      var content = document.getElementById('detail-content');
      if (!content) return;
      var div = document.createElement('div');
      div.innerHTML = html;
      content.appendChild(div);
      wireBacklinkClicks(div);
    });
  }

  function esc(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // Store local graph data when loaded
  JUG.on('localgraph:loaded', function(data) {
    JUG._localGraphData = data;
  });

  // Append backlinks after detail panel opens
  JUG.on('graph:selectNode', function(node) {
    JUG._localGraphData = null;
    // Wait for local graph to load, then render backlinks
    var handler = function(data) {
      JUG._localGraphData = data;
      loadAndRender(node);
    };
    // One-shot listener
    var listeners = [];
    var orig = JUG.on;
    JUG.on('localgraph:loaded', handler);
    // Clean up after 5s
    setTimeout(function() {
      JUG._localGraphData = null;
    }, 5000);
  });

  JUG._backlinks = { loadAndRender: loadAndRender };
})();
