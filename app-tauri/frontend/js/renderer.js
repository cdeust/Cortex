// Cortex Neural Graph — Force Layout & Interaction
// Uses JUG._draw (draw.js) for node canvas rendering
// Uses built-in link renderer for bright visible connections
(function() {
  var graph = null;
  var hoveredNode = null;
  var selectedNode = null;
  var neighborSet = {};

  // Default bright edge color — cyan like the reference image
  var EDGE_DEFAULT = 'rgba(80, 210, 235, 0.12)';
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
      .d3AlphaDecay(0.015)
      .d3VelocityDecay(0.35)
      .warmupTicks(100)
      .cooldownTicks(400)
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
    var focusId = selectedNode ? selectedNode.id : (hoveredNode ? hoveredNode.id : null);
    if (!focusId) return EDGE_DEFAULT;
    var sid = typeof e.source === 'object' ? e.source.id : e.source;
    var tid = typeof e.target === 'object' ? e.target.id : e.target;
    if (sid === focusId || tid === focusId) return EDGE_ACTIVE;
    return EDGE_DIMMED;
  }

  function linkWidth(e) {
    var focusId = selectedNode ? selectedNode.id : (hoveredNode ? hoveredNode.id : null);
    if (!focusId) return 0.4 + (e.weight || 0.3) * 1.2;
    var sid = typeof e.source === 'object' ? e.source.id : e.source;
    var tid = typeof e.target === 'object' ? e.target.id : e.target;
    if (sid === focusId || tid === focusId) return 1.5;
    return 0.15;
  }

  // ── Layout forces ──
  // Tuned for ~1800 nodes. Collision force prevents overlap.
  // Strong hierarchy (category→domain→children) with generous spacing.
  function configureForces() {
    // Guard: d3 is loaded lazily by the workflow_graph renderer and may not
    // be on the page yet when this legacy configurator runs. The whole
    // legacy `ForceGraph()` is stubbed anyway (see workflow_graph_shims.js),
    // so skipping this is a no-op — we only avoid the noisy ReferenceError.
    if (typeof d3 === 'undefined' || !d3.forceCollide) return;
    // Collision detection — the key to preventing overlap.
    // Radius = nodeRadius + padding. This guarantees minimum spacing.
    graph.d3Force('collide', d3.forceCollide(function(n) {
      var base = JUG._draw.nodeRadius(n);
      // Extra padding for structural nodes so they breathe
      var padding = (n.type === 'domain' || n.type === 'category' || n.type === 'root') ? 8
        : (n.type === 'topic' || n.type === 'bridge-entity') ? 5 : 2;
      return base + padding;
    }).iterations(3).strength(0.9));

    graph.d3Force('charge').strength(function(n) {
      return {
        'root': -800, 'category': -400, 'domain': -250,
        'agent': -100, 'type-group': -50,
        'topic': -120, 'bridge-entity': -100,
        'entry-point': -35, 'recurring-pattern': -25,
        'tool-preference': -35, 'behavioral-feature': -30,
        'memory': -20, 'entity': -18,
        'discussion': -18
      }[n.type] || -18;
    }).distanceMax(600);

    graph.d3Force('link')
      .distance(function(e) {
        return {
          'has-category': 180, 'has-project': 130,
          'has-agent': 70, 'has-group': 45, 'groups': 30,
          'bridge': 180, 'persistent-feature': 140,
          'memory-entity': 35, 'domain-entity': 55,
          'has-discussion': 40,
          'topic-member': 20, 'domain-contains': 65, 'co-entity': 55
        }[e.type || 'default'] || 30;
      })
      .strength(function(e) {
        return {
          'has-category': 0.6, 'has-project': 0.5,
          'has-agent': 0.4, 'has-group': 0.4, 'groups': 0.35,
          'bridge': 0.1, 'persistent-feature': 0.1,
          'topic-member': 0.4, 'domain-contains': 0.3, 'co-entity': 0.1
        }[e.type] || 0.3;
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
    var changed = hoveredNode !== node;
    hoveredNode = node;
    document.body.style.cursor = node ? 'pointer' : 'default';
    node ? JUG._tooltip.show(node) : JUG._tooltip.hide();
    // Refresh link styles so edges highlight on hover
    if (changed && graph) {
      graph.linkColor(graph.linkColor());
      graph.linkWidth(graph.linkWidth());
    }
  }

  function handleClick(node) {
    if (!node) return;
    if (selectedNode && selectedNode.id === node.id) deselectNode();
    else selectNode(node);
  }

  function handleBgClick() { deselectNode(); }

  var _emitting = false;

  function selectNode(node) {
    selectedNode = node;
    buildNeighborSet(node.id);
    JUG.state.selectedId = node.id;
    _emitting = true;
    JUG.emit('graph:selectNode', node);
    _emitting = false;
    if (graph) graph.linkColor(graph.linkColor());
  }

  function deselectNode() {
    if (!selectedNode && !JUG.state.selectedId) return;
    selectedNode = null;
    neighborSet = {};
    JUG.state.selectedId = null;
    _emitting = true;
    JUG.emit('graph:deselectNode');
    _emitting = false;
    if (graph) graph.linkColor(graph.linkColor());
  }

  // ── Public API ──
  function setGraphData(nodes, links) {
    if (!graph) return;
    JUG._currentEdges = links;
    graph.graphData({ nodes: nodes, links: links });
    setTimeout(function() { graph.zoomToFit(600, 60); }, 1500);
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

  // ── Brushing/linking: sync selection from other views ──
  JUG.on('graph:selectNode', function(node) {
    if (_emitting || !node || !graph) return;
    if (selectedNode && selectedNode.id === node.id) return;
    // External selection (from board view) — sync graph state
    var data = graph.graphData();
    for (var i = 0; i < data.nodes.length; i++) {
      if (data.nodes[i].id === node.id) {
        selectedNode = data.nodes[i];
        buildNeighborSet(node.id);
        JUG.state.selectedId = node.id;
        graph.linkColor(graph.linkColor());
        return;
      }
    }
    // Node not in graph data — store ID for when we switch to graph view
    JUG.state.selectedId = node.id;
  });

  JUG.on('graph:deselectNode', function() {
    if (_emitting || !selectedNode) return;
    selectedNode = null;
    neighborSet = {};
    JUG.state.selectedId = null;
    if (graph) graph.linkColor(graph.linkColor());
  });

  // ── View switching ──
  JUG.on('state:activeView', function(e) {
    var graphContainer = document.getElementById('graph-container');
    var infoPanel = document.getElementById('info-panel');
    var legend = document.getElementById('legend');
    var statusBar = document.getElementById('status-bar');
    var isGraph = e.value === 'graph';

    if (graphContainer) graphContainer.style.display = isGraph ? 'block' : 'none';
    if (infoPanel) infoPanel.style.display = isGraph ? '' : 'none';
    if (legend) legend.style.display = isGraph ? '' : 'none';
    if (statusBar) statusBar.style.display = isGraph ? '' : 'none';

    if (isGraph) {
      if (graph) graph.resumeAnimation();
      // Restore selection from board view
      if (JUG.state.selectedId && !selectedNode) {
        selectNodeById(JUG.state.selectedId);
      }
    } else {
      if (graph) graph.pauseAnimation();
    }
  });

  JUG.setGraphData = setGraphData;
  JUG.resetCamera = resetView;
  JUG.selectNodeById = selectNodeById;
  JUG.deselectNode = deselectNode;
  JUG.getGraph = function() { return graph; };
})();
