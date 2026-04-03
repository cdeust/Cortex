// Cortex Neural Graph — Local Graph (Obsidian-like neighborhood view)
// Mini force-directed canvas showing a memory's entity neighborhood.
// Triggered on memory node selection; fetches /api/local-graph.
(function() {
  var canvas, ctx, container;
  var nodes = [], edges = [], simulation = null;
  var hoveredNode = null;
  var WIDTH = 360, HEIGHT = 280;
  var DAMPING = 0.92, SPRING_K = 0.04, REPULSION = 800, DT = 0.8;

  var TYPE_COLORS = {
    center_memory: '#E8B840',
    neighbor_memory: '#4488DD',
    entity: '#2DD4BF',
  };

  function init() {
    container = document.getElementById('local-graph-container');
    if (!container) return;
    canvas = document.createElement('canvas');
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    canvas.style.width = '100%';
    canvas.style.height = HEIGHT + 'px';
    canvas.style.cursor = 'pointer';
    container.appendChild(canvas);
    ctx = canvas.getContext('2d');

    canvas.addEventListener('click', onCanvasClick);
    canvas.addEventListener('mousemove', onCanvasMove);
    canvas.addEventListener('mouseleave', function() { hoveredNode = null; draw(); });
  }

  function onCanvasClick(e) {
    var node = hitTest(e);
    if (!node) return;
    if (node.memory_id) {
      loadGraph(node.memory_id);
      JUG.emit('localgraph:navigate', { memory_id: node.memory_id });
    } else if (node.entity_id) {
      JUG.emit('localgraph:entityClick', { entity_id: node.entity_id, name: node.label });
    }
  }

  function onCanvasMove(e) {
    var prev = hoveredNode;
    hoveredNode = hitTest(e);
    if (prev !== hoveredNode) draw();
  }

  function hitTest(e) {
    var rect = canvas.getBoundingClientRect();
    var mx = (e.clientX - rect.left) * (WIDTH / rect.width);
    var my = (e.clientY - rect.top) * (HEIGHT / rect.height);
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var dx = mx - n.x, dy = my - n.y;
      if (dx * dx + dy * dy < n.r * n.r + 16) return n;
    }
    return null;
  }

  function loadGraph(memoryId) {
    var url = '/api/local-graph?memory_id=' + memoryId + '&depth=1';
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
      if (data.error) { clearGraph(); return; }
      buildSimulation(data);
      JUG.emit('localgraph:loaded', data);
    }).catch(function() { clearGraph(); });
  }

  function clearGraph() {
    nodes = [];
    edges = [];
    if (simulation) { clearInterval(simulation); simulation = null; }
    if (ctx) { ctx.clearRect(0, 0, WIDTH, HEIGHT); }
    if (container) container.style.display = 'none';
  }

  function buildSimulation(data) {
    if (simulation) { clearInterval(simulation); simulation = null; }
    if (container) container.style.display = 'block';

    var nodeMap = {};
    nodes = (data.nodes || []).map(function(n, i) {
      var angle = (i / data.nodes.length) * Math.PI * 2;
      var dist = n.type === 'center_memory' ? 0 : 60 + Math.random() * 40;
      var obj = {
        id: n.id,
        label: n.label || '',
        type: n.type,
        memory_id: n.memory_id || null,
        entity_id: n.entity_id || null,
        heat: n.heat || 0.5,
        x: WIDTH / 2 + Math.cos(angle) * dist,
        y: HEIGHT / 2 + Math.sin(angle) * dist,
        vx: 0, vy: 0,
        r: n.type === 'center_memory' ? 10 : n.type === 'entity' ? 6 : 7,
      };
      nodeMap[n.id] = obj;
      return obj;
    });

    edges = (data.edges || []).map(function(e) {
      return { source: nodeMap[e.source], target: nodeMap[e.target], type: e.type, weight: e.weight || 0.5 };
    }).filter(function(e) { return e.source && e.target; });

    var ticks = 0;
    simulation = setInterval(function() {
      stepSimulation();
      draw();
      ticks++;
      if (ticks > 200) { clearInterval(simulation); simulation = null; }
    }, 16);
  }

  function stepSimulation() {
    var i, j, n, m, dx, dy, dist, force;

    // Repulsion between all pairs
    for (i = 0; i < nodes.length; i++) {
      for (j = i + 1; j < nodes.length; j++) {
        n = nodes[i]; m = nodes[j];
        dx = n.x - m.x; dy = n.y - m.y;
        dist = Math.sqrt(dx * dx + dy * dy) || 1;
        force = REPULSION / (dist * dist);
        var fx = (dx / dist) * force, fy = (dy / dist) * force;
        n.vx += fx * DT; n.vy += fy * DT;
        m.vx -= fx * DT; m.vy -= fy * DT;
      }
    }

    // Spring attraction along edges
    for (i = 0; i < edges.length; i++) {
      var e = edges[i];
      dx = e.target.x - e.source.x; dy = e.target.y - e.source.y;
      dist = Math.sqrt(dx * dx + dy * dy) || 1;
      force = (dist - 60) * SPRING_K;
      var sx = (dx / dist) * force, sy = (dy / dist) * force;
      e.source.vx += sx * DT; e.source.vy += sy * DT;
      e.target.vx -= sx * DT; e.target.vy -= sy * DT;
    }

    // Center gravity + damping + bounds
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      n.vx += (WIDTH / 2 - n.x) * 0.002;
      n.vy += (HEIGHT / 2 - n.y) * 0.002;
      n.vx *= DAMPING; n.vy *= DAMPING;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(n.r, Math.min(WIDTH - n.r, n.x));
      n.y = Math.max(n.r, Math.min(HEIGHT - n.r, n.y));
    }
  }

  function draw() {
    if (!ctx) return;
    ctx.clearRect(0, 0, WIDTH, HEIGHT);

    // Edges
    ctx.lineWidth = 1;
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      ctx.strokeStyle = edgeColor(e.type, e.weight);
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.stroke();
    }

    // Nodes
    for (var j = 0; j < nodes.length; j++) {
      var n = nodes[j];
      var col = TYPE_COLORS[n.type] || '#888';
      var isHover = hoveredNode === n;

      // Glow
      if (isHover || n.type === 'center_memory') {
        ctx.shadowColor = col;
        ctx.shadowBlur = isHover ? 12 : 8;
      }
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + (isHover ? 2 : 0), 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // Label
      if (isHover || n.type === 'center_memory') {
        ctx.fillStyle = '#ddd';
        ctx.font = '9px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        var lbl = n.label.length > 30 ? n.label.substring(0, 27) + '...' : n.label;
        ctx.fillText(lbl, n.x, n.y + n.r + 12);
      }
    }
  }

  function edgeColor(type, weight) {
    var alpha = Math.round(Math.max(0.2, Math.min(1, weight)) * 255).toString(16);
    if (alpha.length === 1) alpha = '0' + alpha;
    if (type === 'mention') return '#2DD4BF' + alpha;
    if (type === 'co_entity') return '#4488DD' + alpha;
    if (type === 'relationship') return '#C070D0' + alpha;
    return '#666666' + alpha;
  }

  // Wire into node selection events
  JUG.on('graph:selectNode', function(node) {
    if (node.type === 'memory' && node.memoryId) {
      loadGraph(node.memoryId);
    } else {
      clearGraph();
    }
  });
  JUG.on('graph:deselectNode', clearGraph);

  document.addEventListener('DOMContentLoaded', init);

  JUG._localGraph = { loadGraph: loadGraph, clearGraph: clearGraph };
})();
