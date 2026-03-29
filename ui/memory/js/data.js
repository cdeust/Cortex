// Cortex Memory Dashboard — Data Loading
(function() {
  var CMD = window.CMD;

  CMD.loadCortexData = async function() {
    var res = await fetch('/api/dashboard');
    var raw = await res.json();
    var nodes = [];
    var edges = [];

    // Entities -> nodes
    (raw.entities || []).forEach(function(e) {
      nodes.push({
        id: 'e_' + e.id,
        name: e.name || 'Entity',
        nodeType: 'memory',
        type: e.type || 'reference',
        project: e.domain || 'cortex',
        path: '',
        heat: e.heat || 0,
        connections: 0,
      });
    });

    // Memories -> nodes
    (raw.hot_memories || []).forEach(function(m) {
      var storeType = m.store_type || 'episodic';
      var memType = storeType === 'episodic' ? 'user' : storeType === 'semantic' ? 'project' : 'reference';
      nodes.push({
        id: 'm_' + m.id,
        name: (m.content || '').slice(0, 80),
        nodeType: 'memory',
        type: memType,
        project: m.domain || 'cortex',
        path: '',
        heat: m.heat || 0,
        importance: m.importance || 0.5,
        tags: m.tags || [],
        created_at: m.created_at || '',
        source: m.source || '',
        access_count: m.access_count || 0,
        store_type: storeType,
        connections: 0,
        consolidation_stage: m.consolidation_stage || 'labile',
        schema_match_score: m.schema_match_score || 0,
        interference_score: m.interference_score || 0,
        hippocampal_dependency: m.hippocampal_dependency || 1.0,
        theta_phase: m.theta_phase || 0,
        is_global: !!m.is_global,
      });
    });

    // Relationships -> edges
    (raw.relationships || []).forEach(function(r) {
      edges.push({
        source: 'e_' + r.source,
        target: 'e_' + r.target,
        type: r.is_causal ? 'causal' : (r.type || 'related'),
        weight: r.weight || 0.5,
      });
    });

    // Virtual edges: memories -> best-matching entity
    var entityNodes = nodes.filter(function(n) { return n.id.startsWith('e_'); });
    var memNodes = nodes.filter(function(n) { return n.id.startsWith('m_'); });
    memNodes.forEach(function(mem) {
      var memDomain = (mem.project || '').toLowerCase();
      var memContent = (mem.name + ' ' + (mem.tags || []).join(' ')).toLowerCase();
      var bestId = null, bestScore = 0;
      entityNodes.forEach(function(ent) {
        var entName = (ent.name || '').toLowerCase();
        var entDomain = (ent.project || '').toLowerCase();
        var score = 0;
        if (memDomain && entDomain && memDomain === entDomain) score += 0.5;
        if (entName.length > 2 && memContent.indexOf(entName) >= 0) score += 0.4;
        if (score > bestScore) { bestScore = score; bestId = ent.id; }
      });
      if (!bestId && entityNodes.length > 0) {
        bestId = entityNodes[Math.floor(Math.random() * entityNodes.length)].id;
      }
      if (bestId) {
        edges.push({ source: mem.id, target: bestId, type: 'context', weight: Math.min(bestScore || 0.1, 0.6) });
      }
    });

    return { nodes: nodes, edges: edges, stats: raw.stats };
  };

  CMD.initData = async function() {
    var data;
    if (window.__GRAPH_DATA_URL__) {
      var resp = await fetch(window.__GRAPH_DATA_URL__);
      data = await resp.json();
    } else if (window.__GRAPH_DATA__) {
      data = window.__GRAPH_DATA__;
    } else {
      data = await CMD.loadCortexData();
    }

    CMD.nodes = data.nodes;
    CMD.edges = data.edges;
    CMD.W = window.innerWidth;
    CMD.H = window.innerHeight;

    // Build node map
    CMD.nodes.forEach(function(n) { CMD.nodeMap[n.id] = n; });

    // Count connections
    CMD.edges.forEach(function(e) {
      if (CMD.nodeMap[e.source]) CMD.nodeMap[e.source].connections = (CMD.nodeMap[e.source].connections || 0) + 1;
      if (CMD.nodeMap[e.target]) CMD.nodeMap[e.target].connections = (CMD.nodeMap[e.target].connections || 0) + 1;
    });

    // Categorize nodes
    CMD.hubNs = CMD.nodes.filter(function(n) { return n.nodeType === 'project-hub'; });
    CMD.convNs = CMD.nodes.filter(function(n) { return n.nodeType === 'conversation'; });
    CMD.globalNs = CMD.nodes.filter(function(n) {
      return n.project === '__global__' && n.nodeType !== 'plan' && n.nodeType !== 'todo' && n.nodeType !== 'plugin';
    });
    CMD.planNs = CMD.nodes.filter(function(n) { return n.nodeType === 'plan'; });
    CMD.pluginNs = CMD.nodes.filter(function(n) { return n.nodeType === 'plugin'; });
    CMD.todoNs = CMD.nodes.filter(function(n) { return n.nodeType === 'todo'; });
  };
})();
