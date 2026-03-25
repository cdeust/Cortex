// Cortex Neural Graph — Force-Directed Layout Engine
(function() {
  var layoutNodes = [];
  var layoutEdges = [];
  var layoutClusters = [];
  var alpha = 1.0;
  var alphaDecay = 0.995;
  var running = false;

  // Force strengths by node type
  var CHARGE = {
    'domain': -600,
    'entity': -200,
    'memory': -80,
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
    'co_occurrence': 100,
    'imports': 90,
    'calls': 90,
    'caused_by': 100,
    'resolved_by': 100,
    'decided_to_use': 100,
    'debugged_with': 90,
    'memory-entity': 120,
    'domain-entity': 140,
    'default': 100,
  };

  function initLayout(nodes, edges, clusters) {
    layoutNodes = [];
    layoutEdges = [];
    layoutClusters = clusters || [];
    alpha = 1.0;
    running = true;

    // Initialize positions — use existing Three.js positions if available,
    // otherwise use jittered circular layout grouped by domain
    var domainAngles = {};
    var domainIdx = 0;

    nodes.forEach(function(n, i) {
      var data = n.data || {};
      var domain = data.domain || '';
      var pos = n.group ? n.group.position : null;

      // If node already has a position (re-init after batch add), keep it
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

      if (domainAngles[domain] === undefined) {
        domainAngles[domain] = domainIdx * (Math.PI * 2 / Math.max(Object.keys(domainAngles).length + 5, 5));
        domainIdx++;
      }

      var baseAngle = domainAngles[domain];
      var spread = data.type === 'domain' ? 0 : 40 + Math.random() * 80;
      var jitter = (Math.random() - 0.5) * 1.5;

      layoutNodes.push({
        x: Math.cos(baseAngle + jitter) * (100 + spread) + (Math.random() - 0.5) * 30,
        y: (Math.random() - 0.5) * 120,
        z: Math.sin(baseAngle + jitter) * (100 + spread) + (Math.random() - 0.5) * 30,
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

    // Compute cluster centroids
    layoutClusters.forEach(function(c) {
      c._cx = 0; c._cy = 0; c._cz = 0; c._count = 0;
    });
  }

  function tickLayout() {
    if (!running || alpha < 0.005) { running = false; return; }

    var N = layoutNodes.length;
    if (N === 0) return;

    // Repulsion (direct N²)
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
        if (dist2 > 360000) continue; // distMax = 600

        var charge_j = CHARGE[nj.type] || -100;
        var force = alpha * (charge_i + charge_j) * 0.5 / dist2;
        var fx = dx * force;
        var fy = dy * force;
        var fz = dz * force;

        ni.vx -= fx;
        ni.vy -= fy;
        ni.vz -= fz;
        nj.vx += fx;
        nj.vy += fy;
        nj.vz += fz;
      }
    }

    // Link spring forces
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

      src.vx += fx;
      src.vy += fy;
      src.vz += fz;
      tgt.vx -= fx;
      tgt.vy -= fy;
      tgt.vz -= fz;
    }

    // Centering force
    for (var ci = 0; ci < N; ci++) {
      var nc = layoutNodes[ci];
      nc.vx -= nc.x * 0.001 * alpha;
      nc.vy -= nc.y * 0.001 * alpha;
      nc.vz -= nc.z * 0.001 * alpha;
    }

    // Apply velocity with damping
    for (var vi = 0; vi < N; vi++) {
      var nv = layoutNodes[vi];
      nv.vx *= 0.88;
      nv.vy *= 0.88;
      nv.vz *= 0.88;
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

  // Incrementally add nodes + edges to a running simulation
  function addToLayout(newNodes, newEdges) {
    var baseIdx = layoutNodes.length;

    newNodes.forEach(function(n, i) {
      var data = n.data || {};
      var pos = n.group ? n.group.position : null;

      layoutNodes.push({
        x: pos ? pos.x : (Math.random() - 0.5) * 200,
        y: pos ? pos.y : (Math.random() - 0.5) * 200,
        z: pos ? pos.z : (Math.random() - 0.5) * 200,
        vx: 0, vy: 0, vz: 0,
        type: data.type || 'memory',
        domain: data.domain || '',
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

    // Nudge alpha so simulation resumes gently
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
})();
