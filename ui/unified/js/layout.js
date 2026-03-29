// Cortex Neural Graph — Force-Directed Layout Engine with Domain Clustering
(function() {
  var layoutNodes = [];
  var layoutEdges = [];
  var layoutClusters = [];
  var domainCenters = {};
  var alpha = 1.0;
  var alphaDecay = 0.995;
  var running = false;

  // Force strengths by node type
  var CHARGE = {
    'domain': -600,
    'entity': -150,
    'memory': -60,
    'entry-point': -120,
    'recurring-pattern': -120,
    'tool-preference': -100,
    'behavioral-feature': -80,
  };

  // Link rest length by edge type
  var LINK_DIST = {
    'bridge': 300,
    'persistent-feature': 250,
    'has-entry': 70,
    'has-pattern': 80,
    'uses-tool': 70,
    'has-feature': 60,
    'co_occurrence': 80,
    'imports': 70,
    'calls': 70,
    'defines': 60,
    'extends': 80,
    'caused_by': 100,
    'resolved_by': 100,
    'decided_to_use': 100,
    'debugged_with': 90,
    'memory-entity': 100,
    'domain-entity': 120,
    'default': 90,
  };

  // Domain cluster layout — spacing between project "brains"
  var CLUSTER_RADIUS = 350;   // Distance from origin to each domain center
  var CLUSTER_GRAVITY = 0.012; // Pull toward domain center
  var INTER_CLUSTER_REPEL = 800; // Push between different domain centers

  function _computeDomainCenters(nodes) {
    // Count nodes per domain
    var domainCounts = {};
    nodes.forEach(function(n) {
      var d = (n.data || {}).domain || '';
      if (d) domainCounts[d] = (domainCounts[d] || 0) + 1;
    });

    // Sort domains by node count (largest first = center)
    var domains = Object.keys(domainCounts).sort(function(a, b) {
      return domainCounts[b] - domainCounts[a];
    });

    // Assign centers on a circle (largest domain nearest camera)
    var centers = {};
    var n = Math.max(domains.length, 1);
    domains.forEach(function(d, i) {
      var angle = (i / n) * Math.PI * 2 - Math.PI / 2;
      var r = n === 1 ? 0 : CLUSTER_RADIUS;
      centers[d] = {
        x: Math.cos(angle) * r,
        y: 0,
        z: Math.sin(angle) * r,
        count: domainCounts[d],
        angle: angle,
      };
    });
    return centers;
  }

  function initLayout(nodes, edges, clusters) {
    layoutNodes = [];
    layoutEdges = [];
    layoutClusters = clusters || [];
    alpha = 1.0;
    running = true;

    // Compute domain centers
    domainCenters = _computeDomainCenters(nodes);

    // Initialize positions — place nodes near their domain center
    nodes.forEach(function(n, i) {
      var data = n.data || {};
      var domain = data.domain || '';
      var pos = n.group ? n.group.position : null;

      // If node already has a position, keep it
      if (pos && (pos.x !== 0 || pos.y !== 0 || pos.z !== 0)) {
        layoutNodes.push({
          x: pos.x, y: pos.y, z: pos.z,
          vx: 0, vy: 0, vz: 0,
          type: data.type || 'memory',
          domain: domain,
          idx: i,
        });
        return;
      }

      // Start near domain center with jitter
      var center = domainCenters[domain] || { x: 0, y: 0, z: 0 };
      var spread = data.type === 'domain' ? 0 : 30 + Math.random() * 60;
      var jx = (Math.random() - 0.5) * spread;
      var jy = (Math.random() - 0.5) * spread;
      var jz = (Math.random() - 0.5) * spread;

      layoutNodes.push({
        x: center.x + jx,
        y: center.y + jy,
        z: center.z + jz,
        vx: 0, vy: 0, vz: 0,
        type: data.type || 'memory',
        domain: domain,
        idx: i,
      });
    });

    // Process edges
    edges.forEach(function(e) {
      layoutEdges.push({
        srcIdx: e.srcIdx,
        tgtIdx: e.tgtIdx,
        weight: e.weight || 0.3,
        type: e.type || 'default',
      });
    });
  }

  function tickLayout() {
    if (!running || alpha < 0.005) { running = false; return; }

    var N = layoutNodes.length;
    if (N === 0) return;

    // 1. Repulsion (N² — only between nearby nodes)
    for (var i = 0; i < N; i++) {
      var ni = layoutNodes[i];
      var charge_i = CHARGE[ni.type] || -100;

      for (var j = i + 1; j < N; j++) {
        var nj = layoutNodes[j];
        var dx = ni.x - nj.x;
        var dy = ni.y - nj.y;
        var dz = ni.z - nj.z;
        var dist2 = dx * dx + dy * dy + dz * dz;
        if (dist2 < 1) dist2 = 1;
        if (dist2 > 250000) continue;

        // Stronger repulsion between different domains
        var crossDomain = ni.domain !== nj.domain && ni.domain && nj.domain;
        var charge_j = CHARGE[nj.type] || -100;
        var multiplier = crossDomain ? 2.0 : 1.0;
        var force = alpha * (charge_i + charge_j) * 0.5 * multiplier / dist2;
        var fx = dx * force;
        var fy = dy * force;
        var fz = dz * force;

        ni.vx -= fx; ni.vy -= fy; ni.vz -= fz;
        nj.vx += fx; nj.vy += fy; nj.vz += fz;
      }
    }

    // 2. Link spring forces
    for (var li = 0; li < layoutEdges.length; li++) {
      var e = layoutEdges[li];
      var src = layoutNodes[e.srcIdx];
      var tgt = layoutNodes[e.tgtIdx];
      if (!src || !tgt) continue;

      var dx = tgt.x - src.x;
      var dy = tgt.y - src.y;
      var dz = tgt.z - src.z;
      var dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist < 0.1) dist = 0.1;

      var restLen = LINK_DIST[e.type] || LINK_DIST['default'];
      var k = 0.02 * e.weight * alpha;
      var displacement = (dist - restLen) / dist;
      var fx = dx * displacement * k;
      var fy = dy * displacement * k;
      var fz = dz * displacement * k;

      src.vx += fx; src.vy += fy; src.vz += fz;
      tgt.vx -= fx; tgt.vy -= fy; tgt.vz -= fz;
    }

    // 3. Domain cluster gravity — pull nodes toward their domain center
    for (var ci = 0; ci < N; ci++) {
      var nc = layoutNodes[ci];
      var center = domainCenters[nc.domain];
      if (center) {
        var dx = center.x - nc.x;
        var dy = center.y - nc.y;
        var dz = center.z - nc.z;
        nc.vx += dx * CLUSTER_GRAVITY * alpha;
        nc.vy += dy * CLUSTER_GRAVITY * alpha;
        nc.vz += dz * CLUSTER_GRAVITY * alpha;
      } else {
        // No domain — gentle centering
        nc.vx -= nc.x * 0.001 * alpha;
        nc.vy -= nc.y * 0.001 * alpha;
        nc.vz -= nc.z * 0.001 * alpha;
      }
    }

    // 4. Apply velocity with damping
    for (var vi = 0; vi < N; vi++) {
      var nv = layoutNodes[vi];
      nv.vx *= 0.86;
      nv.vy *= 0.86;
      nv.vz *= 0.86;
      nv.x += nv.vx;
      nv.y += nv.vy;
      nv.z += nv.vz;
    }

    alpha *= alphaDecay;
  }

  function warmUp(ticks) {
    for (var t = 0; t < ticks; t++) {
      tickLayout();
    }
  }

  function restartLayout(a) {
    alpha = a || 0.3;
    running = true;
  }

  function getPositions() {
    return layoutNodes;
  }

  function isRunning() {
    return running;
  }

  function getDomainCenters() {
    return domainCenters;
  }

  // Incrementally add nodes + edges to a running simulation
  function addToLayout(newNodes, newEdges) {
    var baseIdx = layoutNodes.length;

    // Recompute domain centers with new nodes included
    var allNodeData = layoutNodes.map(function(n) {
      return { data: { domain: n.domain, type: n.type } };
    }).concat(newNodes);
    domainCenters = _computeDomainCenters(allNodeData);

    newNodes.forEach(function(n, i) {
      var data = n.data || {};
      var domain = data.domain || '';
      var center = domainCenters[domain] || { x: 0, y: 0, z: 0 };

      layoutNodes.push({
        x: center.x + (Math.random() - 0.5) * 60,
        y: center.y + (Math.random() - 0.5) * 60,
        z: center.z + (Math.random() - 0.5) * 60,
        vx: 0, vy: 0, vz: 0,
        type: data.type || 'memory',
        domain: domain,
        idx: baseIdx + i,
      });
    });

    newEdges.forEach(function(e) {
      layoutEdges.push({
        srcIdx: e.srcIdx,
        tgtIdx: e.tgtIdx,
        weight: e.weight || 0.3,
        type: e.type || 'default',
      });
    });

    alpha = Math.max(alpha, 0.15);
    running = true;
  }

  JUG.initLayout = initLayout;
  JUG.tickLayout = tickLayout;
  JUG.warmUp = warmUp;
  JUG.restartLayout = restartLayout;
  JUG.addToLayout = addToLayout;
  JUG.getLayoutPositions = getPositions;
  JUG.isLayoutRunning = isRunning;
  JUG.getDomainCenters = getDomainCenters;
})();
