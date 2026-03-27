// Cortex Neural Graph — Force Layout & Interaction
// Uses JUG._draw (draw.js) for node canvas rendering
// Uses built-in link renderer for bright visible connections
(function() {
  var graph = null;
  var hoveredNode = null;
  var selectedNode = null;
  var neighborSet = {};

  // Default bright edge color — cyan like the reference image
  var EDGE_DEFAULT = 'rgba(80, 210, 235, 0.45)';
  var EDGE_DIMMED  = 'rgba(80, 210, 235, 0.04)';
  var EDGE_ACTIVE  = 'rgba(240, 210, 100, 0.9)';

  function init() {
    var container = document.getElementById('graph-container');
    if (!container) return;

    graph = ForceGraph()(container)
      .backgroundColor('#080810')
      .nodeId('id')
      .nodeLabel(null)
      .nodeCanvasObject(drawNode)
      .nodeCanvasObjectMode(function() { return 'replace'; })
      .nodePointerAreaPaint(JUG._draw.hitArea)
      .linkSource('source')
      .linkTarget('target')
      // Built-in link renderer — bright and visible
      .linkColor(linkColor)
      .linkWidth(linkWidth)
      .linkCurvature(function(e) {
        return (e.type === 'bridge' || e.type === 'persistent-feature') ? 0.15 : 0;
      })
      .linkDirectionalParticles(function(e) {
        if (!selectedNode) return 0;
        var sid = typeof e.source === 'object' ? e.source.id : e.source;
        var tid = typeof e.target === 'object' ? e.target.id : e.target;
        return (sid === selectedNode.id || tid === selectedNode.id) ? 3 : 0;
      })
      .linkDirectionalParticleWidth(1.5)
      .linkDirectionalParticleColor(function() { return '#F0D870'; })
      .linkDirectionalParticleSpeed(0.006)
      .d3AlphaDecay(0.012)
      .d3VelocityDecay(0.45)
      .warmupTicks(300)
      .cooldownTicks(500)
      .onNodeHover(handleHover)
      .onNodeClick(handleClick)
      .onBackgroundClick(handleBgClick);

    configureForces();

    window.addEventListener('resize', function() {
      graph.width(container.clientWidth).height(container.clientHeight);
    });
  }

  // ── Link styling — bright cyan like reference image ──
  function linkColor(e) {
    if (!selectedNode) return EDGE_DEFAULT;
    var sid = typeof e.source === 'object' ? e.source.id : e.source;
    var tid = typeof e.target === 'object' ? e.target.id : e.target;
    if (sid === selectedNode.id || tid === selectedNode.id) return EDGE_ACTIVE;
    return EDGE_DIMMED;
  }

  function linkWidth(e) {
    if (!selectedNode) return 0.4 + (e.weight || 0.3) * 1.2;
    var sid = typeof e.source === 'object' ? e.source.id : e.source;
    var tid = typeof e.target === 'object' ? e.target.id : e.target;
    if (sid === selectedNode.id || tid === selectedNode.id) return 1.5;
    return 0.15;
  }

  // ── Layout forces ──
  function configureForces() {
    graph.d3Force('charge').strength(function(n) {
      return {
        'root': -300, 'category': -150, 'domain': -100,
        'agent': -50, 'type-group': -20,
        'entry-point': -15, 'recurring-pattern': -10,
        'tool-preference': -15, 'behavioral-feature': -12,
        'memory': -15, 'entity': -12
      }[n.type] || -12;
    }).distanceMax(300);

    graph.d3Force('link')
      .distance(function(e) {
        return {
          'has-category': 80, 'has-project': 60,
          'has-agent': 35, 'has-group': 22, 'groups': 15,
          'bridge': 80, 'persistent-feature': 70,
          'memory-entity': 25, 'domain-entity': 30
        }[e.type || 'default'] || 18;
      })
      .strength(function(e) {
        return {
          'has-category': 0.7, 'has-project': 0.6,
          'has-agent': 0.5, 'has-group': 0.5, 'groups': 0.4,
          'bridge': 0.15, 'persistent-feature': 0.15
        }[e.type] || 0.35;
      });
  }

  // ── Node drawing delegates to draw.js ──
  function drawNode(node, ctx, globalScale) {
    var hid = hoveredNode ? hoveredNode.id : null;
    var sid = selectedNode ? selectedNode.id : null;
    JUG._draw.node(node, ctx, globalScale, hid, sid, neighborSet);
  }

  // ── Neighbor precomputation ──
  function buildNeighborSet(nodeId) {
    neighborSet = {};
    neighborSet[nodeId] = true;
    var edges = JUG._currentEdges || [];
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === nodeId) neighborSet[tid] = true;
      if (tid === nodeId) neighborSet[sid] = true;
    }
  }

  // ── Interaction ──
  function handleHover(node) {
    hoveredNode = node;
    document.body.style.cursor = node ? 'pointer' : 'default';
    node ? showTooltip(node) : hideTooltip();
  }

  function handleClick(node) {
    if (!node) return;
    if (selectedNode && selectedNode.id === node.id) deselectNode();
    else selectNode(node);
  }

  function handleBgClick() { deselectNode(); }

  function selectNode(node) {
    selectedNode = node;
    buildNeighborSet(node.id);
    JUG.state.selectedId = node.id;
    JUG.emit('graph:selectNode', node);
    // Force re-render to update link colors/particles
    if (graph) graph.linkColor(graph.linkColor());
  }

  function deselectNode() {
    selectedNode = null;
    neighborSet = {};
    JUG.state.selectedId = null;
    JUG.emit('graph:deselectNode');
    if (graph) graph.linkColor(graph.linkColor());
  }

  // ── Tooltip ──
  function buildMeta(d) {
    var m = [];
    if (d.quality !== undefined) {
      var q = d.quality;
      var ql = q >= 0.6 ? 'Strong' : q >= 0.3 ? 'Moderate' : 'Weak';
      m.push('Quality: ' + (q * 100).toFixed(0) + '% (' + ql + ')');
    }
    if (d.domain) m.push('Domain: ' + d.domain);
    if (d.heat !== undefined) m.push('Heat: ' + d.heat);
    if (d.importance !== undefined) m.push('Imp: ' + d.importance);
    if (d.sessionCount !== undefined) m.push('Sessions: ' + d.sessionCount);
    if (d.confidence !== undefined) m.push('Conf: ' + Math.round(d.confidence * 100) + '%');
    if (d.frequency !== undefined) m.push('Freq: ' + d.frequency);
    if (d.ratio !== undefined) m.push('Usage: ' + Math.round(d.ratio * 100) + '%');
    if (d.entityType) m.push('Type: ' + d.entityType);
    if (d.emotion && d.emotion !== 'neutral') m.push('Emotion: ' + d.emotion);
    return m.join('\n');
  }

  function showTooltip(data) {
    var tip = document.getElementById('tooltip');
    if (!tip) return;
    var el = document.getElementById('tt-label');
    var ty = document.getElementById('tt-type');
    var me = document.getElementById('tt-meta');
    if (el) el.textContent = data.label || '';
    if (ty) {
      ty.textContent = JUG.NODE_LABELS[data.type] || data.type;
      ty.style.color = JUG.getNodeColor(data);
    }
    if (me) me.textContent = buildMeta(data);
    tip.classList.add('visible');
    var handler = function(e) {
      var tx = e.clientX + 16, tty = e.clientY + 16;
      if (tx + 260 > innerWidth) tx = e.clientX - 276;
      if (tty + 120 > innerHeight) tty = e.clientY - 136;
      tip.style.left = tx + 'px'; tip.style.top = tty + 'px';
    };
    window.addEventListener('mousemove', handler);
    tip._moveHandler = handler;
  }

  function hideTooltip() {
    var tip = document.getElementById('tooltip');
    if (!tip) return;
    tip.classList.remove('visible');
    if (tip._moveHandler) {
      window.removeEventListener('mousemove', tip._moveHandler);
      tip._moveHandler = null;
    }
  }

  // ── Public API ──
  function setGraphData(nodes, links) {
    if (!graph) return;
    JUG._currentEdges = links;
    graph.graphData({ nodes: nodes, links: links });
    setTimeout(function() { graph.zoomToFit(800, 80); }, 2500);
  }

  function resetView() {
    deselectNode();
    if (graph) graph.zoomToFit(400, 40);
  }

  function selectNodeById(nodeId) {
    var data = graph ? graph.graphData() : { nodes: [] };
    for (var i = 0; i < data.nodes.length; i++) {
      if (data.nodes[i].id === nodeId) {
        selectNode(data.nodes[i]);
        graph.centerAt(data.nodes[i].x, data.nodes[i].y, 800);
        graph.zoom(4, 800);
        return true;
      }
    }
    return false;
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    requestAnimationFrame(init);
  }

  JUG.setGraphData = setGraphData;
  JUG.resetCamera = resetView;
  JUG.selectNodeById = selectNodeById;
  JUG.deselectNode = deselectNode;
  JUG.getGraph = function() { return graph; };
})();
