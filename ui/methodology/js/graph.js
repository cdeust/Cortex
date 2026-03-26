// Cortex Methodology Map — Graph
window.CMV = window.CMV || {};

/**
 * Build the 3D force graph from filtered data.
 * Configures node rendering, link styling, interactions, and force tuning.
 * @param {Object} data - Filtered graph data with nodes, edges, blindSpotRegions.
 */
CMV.build = function (data) {
  CMV.graphData = data;
  var tip = document.getElementById('tooltip');

  var fgData = {
    nodes: data.nodes.map(function (n) { return Object.assign({}, n); }),
    links: data.edges.map(function (e) { return Object.assign({}, e); }),
  };

  CMV.graph = ForceGraph3D({ controlType: 'orbit' })(document.getElementById('graph-canvas'))
    .width(innerWidth).height(innerHeight)
    .backgroundColor('#0A0A0F')
    .showNavInfo(false)
    .graphData(fgData)
    .nodeId('id')
    .nodeLabel(function () { return ''; })
    .nodeOpacity(1)
    .nodeThreeObject(function (node) {
      var col = CMV.COLORS[node.type] || '#00FFFF';
      var sz = node.type === 'domain'
        ? Math.max(3, Math.min(8, Math.sqrt(node.sessionCount || 1) * 1.2))
        : Math.max(1.5, Math.min(4, (node.size || 4) * 0.3));

      var group = CMV.createGlowSphere(col, sz);

      if (node.type === 'domain') {
        var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: CMV.makeLabel(node.label),
          transparent: true, depthWrite: false,
        }));
        sprite.scale.set(sz * 14, sz * 3.5, 1);
        sprite.position.set(0, sz * 1.8, 0);
        group.add(sprite);
      }

      return group;
    })
    .nodeThreeObjectExtend(false)
    .linkColor(function (l) {
      if (l.type === 'bridge') return '#FF00FF';
      if (l.type === 'has-blindspot') return 'rgba(50,50,68,0.2)';
      return 'rgba(0,255,255,' + (0.04 + (l.weight || 0.5) * 0.12) + ')';
    })
    .linkWidth(function (l) {
      if (l.type === 'bridge') return 1.5;
      if (l.type === 'has-blindspot') return 0.2;
      return 0.15 + (l.weight || 0.5) * 0.8;
    })
    .linkOpacity(0.8)
    .linkCurvature(function (l) { return l.type === 'bridge' ? 0.4 : 0.05; })
    .linkDirectionalParticles(function (l) {
      if (l.type === 'bridge') return 5;
      if (l.type === 'has-blindspot') return 0;
      return (l.weight || 0) > 0.5 ? 2 : 1;
    })
    .linkDirectionalParticleColor(function (l) {
      return l.type === 'bridge' ? '#FF00FF' : '#00FFFF';
    })
    .linkDirectionalParticleWidth(function (l) {
      return l.type === 'bridge' ? 1.5 : 0.8;
    })
    .linkDirectionalParticleSpeed(function (l) {
      return l.type === 'bridge' ? 0.005 : 0.003;
    })
    .onNodeClick(function (n, ev) {
      ev.stopPropagation();
      if (CMV.selectedId === n.id) { CMV.closeDetail(); return; }
      CMV.selectedId = n.id;
      CMV.focused = true;
      var conn = CMV.getConnected(n.id);
      CMV.graph.nodeOpacity(function (x) { return conn.has(x.id) ? 1 : 0.05; });
      CMV.openDetail(n);
      var dist = 80;
      var r = 1 + dist / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
      CMV.graph.cameraPosition(
        { x: (n.x || 0) * r, y: (n.y || 0) * r, z: (n.z || 0) * r },
        { x: n.x || 0, y: n.y || 0, z: n.z || 0 }, 1200
      );
    })
    .onNodeHover(function (n) {
      document.body.style.cursor = n ? 'pointer' : 'default';
      if (n) {
        CMV.showTip(n, CMV.mouse.x, CMV.mouse.y);
      } else {
        tip.classList.remove('visible');
      }
    })
    .onBackgroundClick(function () { CMV.closeDetail(); });

  // Force tuning — spread nodes far apart
  CMV.graph.d3Force('charge').strength(function (n) {
    return n.type === 'domain' ? -800 : -120;
  }).distanceMax(500);

  CMV.graph.d3Force('link')
    .distance(function (l) {
      if (l.type === 'bridge') return 300;
      if (l.type === 'has-entry') return 80;
      if (l.type === 'has-pattern') return 100;
      if (l.type === 'uses-tool') return 90;
      if (l.type === 'has-blindspot') return 120;
      return 80;
    })
    .strength(function (l) { return l.type === 'bridge' ? 0.05 : 0.3; });

  CMV.graph.d3Force('center').strength(0.02);

  CMV.updateStats(data);
};

/**
 * Post-processing: fog, ambient light, tone mapping.
 */
CMV.setupScene = function () {
  setTimeout(function () {
    try {
      var r = CMV.graph.renderer();
      r.toneMapping = THREE.ACESFilmicToneMapping;
      r.toneMappingExposure = 1.6;

      var scene = CMV.graph.scene();
      scene.fog = new THREE.FogExp2(0x0A0A0F, 0.0006);
      scene.add(new THREE.AmbientLight(0x00FFFF, 0.015));

      var pt = new THREE.PointLight(0x00FFFF, 0.3, 400);
      pt.position.set(0, 0, 0);
      scene.add(pt);
    } catch (e) { /* scene not ready */ }
  }, 600);
};
