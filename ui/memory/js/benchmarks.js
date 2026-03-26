// Cortex Memory Dashboard — 3D Benchmark Visualization
(function() {
  var CMD = window.CMD;

  CMD.BENCHMARKS = {
    longmemeval: { label: 'LongMemEval', recall_10: 97.0, mrr: 0.855, questions: 500, paper_best: 78.4, color: '#00d2ff' },
    locomo:      { label: 'LoCoMo',      recall_10: 84.4, mrr: 0.599, questions: 1982, paper_best: 50.0, color: '#26de81' },
    beam:        { label: 'BEAM',         recall_10: 67.5, mrr: 0.517, questions: 395,  paper_best: 32.9, color: '#d946ef',
      abilities: {
        'Temporal':      0.814,
        'Contradiction': 0.846,
        'Knowledge':     0.800,
        'Multi-hop':     0.755,
        'Extraction':    0.403,
        'Events':        0.407,
        'Preference':    0.407,
        'Summary':       0.332,
        'Instruction':   0.256,
        'Abstention':    0.150
      }
    }
  };

  // Benchmark cluster position — bottom-front of brain, distinct from memory neurons
  var CLUSTER_CENTER = { x: 0, y: -95, z: 100 };
  var benchGroup;

  function makeRingGeo(innerR, outerR, segments) {
    var shape = new THREE.Shape();
    shape.absarc(0, 0, outerR, 0, Math.PI * 2, false);
    var hole = new THREE.Path();
    hole.absarc(0, 0, innerR, 0, Math.PI * 2, true);
    shape.holes.push(hole);
    return new THREE.ShapeGeometry(shape, segments || 48);
  }

  function makeScoreRing(score, maxScore, radius, color, thickness) {
    var pct = score / maxScore;
    var geo = new THREE.RingGeometry(radius - thickness, radius, 48, 1, 0, Math.PI * 2 * pct);
    var mat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(color), transparent: true, opacity: 0.85,
      side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false
    });
    return new THREE.Mesh(geo, mat);
  }

  function makeLabel(text, color, size) {
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    canvas.width = 256; canvas.height = 64;
    ctx.font = 'bold ' + (size || 20) + 'px SF Mono, Fira Code, monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = color || '#ffffff';
    ctx.shadowColor = color || '#00d2ff'; ctx.shadowBlur = 8;
    ctx.fillText(text, 128, 32);
    var tex = new THREE.CanvasTexture(canvas);
    var mat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.9, depthWrite: false });
    var sprite = new THREE.Sprite(mat);
    sprite.scale.set(30, 7.5, 1);
    return sprite;
  }

  function makeScoreLabel(value, unit, color) {
    var text = unit === '%' ? value.toFixed(1) + '%' : value.toFixed(3);
    return makeLabel(text, color, 24);
  }

  function buildBenchmarkSphere(bench, offset) {
    var group = new THREE.Group();
    group.position.set(CLUSTER_CENTER.x + offset.x, CLUSTER_CENTER.y + offset.y, CLUSTER_CENTER.z + offset.z);

    var scoreNorm = bench.recall_10 / 100;
    var coreR = 6 + scoreNorm * 8;

    // Core sphere — size = R@10, glow = MRR
    var coreMat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(bench.color).multiplyScalar(0.2),
      emissive: new THREE.Color(bench.color),
      emissiveIntensity: 0.3 + bench.mrr * 0.7,
      transparent: true, opacity: 0.9, roughness: 0.2, metalness: 0.1
    });
    var core = new THREE.Mesh(new THREE.IcosahedronGeometry(coreR, 2), coreMat);
    group.add(core);

    // Outer glow shell
    var glowMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(bench.color), transparent: true, opacity: 0.08,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.BackSide
    });
    group.add(new THREE.Mesh(new THREE.SphereGeometry(coreR * 1.6, 16, 12), glowMat));

    // Score ring — R@10 arc (partial ring)
    var ring = makeScoreRing(bench.recall_10, 100, coreR + 3, bench.color, 1.2);
    ring.rotation.x = Math.PI / 2;
    group.add(ring);

    // Paper baseline ring (dimmer, red)
    if (bench.paper_best) {
      var baseRing = makeScoreRing(bench.paper_best, 100, coreR + 5, '#ff4444', 0.6);
      baseRing.rotation.x = Math.PI / 2;
      group.add(baseRing);
    }

    // Label
    var label = makeLabel(bench.label, bench.color, 18);
    label.position.set(0, coreR + 8, 0);
    group.add(label);

    // Score readout
    var scoreSpr = makeScoreLabel(bench.recall_10, '%', bench.color);
    scoreSpr.position.set(0, -coreR - 6, 0);
    group.add(scoreSpr);

    // Store for interaction
    core.userData.node = {
      id: 'bench_' + bench.label.toLowerCase(),
      name: bench.label + ' Benchmark',
      nodeType: 'benchmark',
      type: 'benchmark',
      project: 'cortex',
      heat: bench.mrr,
      importance: bench.recall_10 / 100,
      recall_10: bench.recall_10,
      mrr: bench.mrr,
      questions: bench.questions,
      paper_best: bench.paper_best,
      abilities: bench.abilities || null,
      _mesh: core, _baseEmit: coreMat.emissiveIntensity
    };
    core.userData.node._mesh = core;

    return group;
  }

  function buildAbilityNodes(beam, parentPos) {
    var abilities = beam.abilities;
    if (!abilities) return;
    var keys = Object.keys(abilities);
    var count = keys.length;

    keys.forEach(function(key, i) {
      var score = abilities[key];
      var angle = (i / count) * Math.PI * 2;
      var spreadR = 28;
      var x = parentPos.x + Math.cos(angle) * spreadR;
      var z = parentPos.z + Math.sin(angle) * spreadR;
      var y = parentPos.y + (Math.random() - 0.5) * 10;

      var r = 1.5 + score * 3;
      var hue = score > 0.7 ? '#26de81' : score > 0.4 ? '#ffaa00' : '#ff4444';
      var mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(hue).multiplyScalar(0.2),
        emissive: new THREE.Color(hue),
        emissiveIntensity: 0.2 + score * 0.6,
        transparent: true, opacity: 0.85, roughness: 0.3, metalness: 0.1
      });
      var mesh = new THREE.Mesh(new THREE.OctahedronGeometry(r, 0), mat);
      mesh.position.set(x, y, z);
      mesh.userData.node = {
        id: 'beam_' + key.toLowerCase(),
        name: key, nodeType: 'benchmark-ability', type: 'benchmark',
        project: 'BEAM', heat: score, importance: score,
        mrr: score, _mesh: mesh, _baseEmit: mat.emissiveIntensity
      };
      mesh.userData.node._mesh = mesh;
      benchGroup.add(mesh);
      CMD.neuronGroup.add(mesh);

      // Fiber to parent BEAM sphere
      var lineMat = new THREE.LineBasicMaterial({
        color: new THREE.Color(hue), transparent: true, opacity: 0.15 + score * 0.25,
        blending: THREE.AdditiveBlending, depthWrite: false
      });
      var pts = [new THREE.Vector3(x, y, z), new THREE.Vector3(parentPos.x, parentPos.y, parentPos.z)];
      benchGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat));
    });
  }

  CMD.buildBenchmarks = function() {
    benchGroup = new THREE.Group();
    benchGroup.name = 'benchmarks';

    var B = CMD.BENCHMARKS;
    var spacing = 55;

    // Three main benchmark spheres
    var lme = buildBenchmarkSphere(B.longmemeval, { x: -spacing, y: 0, z: 0 });
    var loc = buildBenchmarkSphere(B.locomo,      { x: 0,        y: 0, z: 0 });
    var bm  = buildBenchmarkSphere(B.beam,        { x: spacing,  y: 0, z: 0 });
    benchGroup.add(lme); benchGroup.add(loc); benchGroup.add(bm);

    // Add benchmark cores to neuronGroup for raycasting
    lme.children.forEach(function(c) { if (c.userData.node) CMD.neuronGroup.add(c); });
    loc.children.forEach(function(c) { if (c.userData.node) CMD.neuronGroup.add(c); });
    bm.children.forEach(function(c)  { if (c.userData.node) CMD.neuronGroup.add(c); });

    // BEAM ability satellite nodes
    var beamPos = { x: CLUSTER_CENTER.x + spacing, y: CLUSTER_CENTER.y, z: CLUSTER_CENTER.z };
    buildAbilityNodes(B.beam, beamPos);

    // Cluster label
    var clusterLabel = makeLabel('BENCHMARKS', '#88bbdd', 14);
    clusterLabel.position.set(CLUSTER_CENTER.x, CLUSTER_CENTER.y + 30, CLUSTER_CENTER.z);
    clusterLabel.scale.set(40, 10, 1);
    benchGroup.add(clusterLabel);

    // Connecting fibers between the 3 benchmarks
    var hubPts = [
      new THREE.Vector3(CLUSTER_CENTER.x - spacing, CLUSTER_CENTER.y, CLUSTER_CENTER.z),
      new THREE.Vector3(CLUSTER_CENTER.x, CLUSTER_CENTER.y, CLUSTER_CENTER.z),
      new THREE.Vector3(CLUSTER_CENTER.x + spacing, CLUSTER_CENTER.y, CLUSTER_CENTER.z)
    ];
    var fiberMat = new THREE.LineBasicMaterial({
      color: 0x88bbdd, transparent: true, opacity: 0.12,
      blending: THREE.AdditiveBlending, depthWrite: false
    });
    benchGroup.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([hubPts[0], hubPts[1]]), fiberMat
    ));
    benchGroup.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([hubPts[1], hubPts[2]]), fiberMat
    ));

    CMD.scene.add(benchGroup);
  };

  // Extend detail panel to show benchmark info
  var origOpen = CMD.openPanel;
  CMD.openPanelBenchmark = function(node) {
    if (node.nodeType === 'benchmark') {
      var el = document.getElementById;
      document.getElementById('panel-type').textContent = 'BENCHMARK';
      document.getElementById('panel-type').style.color = '#00d2ff';
      document.getElementById('panel-type').style.borderColor = 'rgba(0,210,255,0.3)';
      document.getElementById('panel-name').textContent = node.name;
      document.getElementById('panel-proj').textContent = node.questions + ' questions';
      var desc = 'R@10: ' + node.recall_10.toFixed(1) + '%\nMRR: ' + node.mrr.toFixed(3);
      if (node.paper_best) desc += '\nPaper best: ' + node.paper_best + '%';
      if (node.abilities) {
        desc += '\n\nAbilities:';
        Object.keys(node.abilities).forEach(function(k) {
          desc += '\n  ' + k + ': ' + node.abilities[k].toFixed(3);
        });
      }
      document.getElementById('panel-desc').textContent = desc;
      document.getElementById('panel').classList.add('open');
      return true;
    }
    if (node.nodeType === 'benchmark-ability') {
      document.getElementById('panel-type').textContent = 'BEAM ABILITY';
      document.getElementById('panel-type').style.color = node.mrr > 0.7 ? '#26de81' : node.mrr > 0.4 ? '#ffaa00' : '#ff4444';
      document.getElementById('panel-type').style.borderColor = 'rgba(255,255,255,0.15)';
      document.getElementById('panel-name').textContent = node.name;
      document.getElementById('panel-proj').textContent = 'BEAM (ICLR 2026)';
      document.getElementById('panel-desc').textContent = 'MRR: ' + node.mrr.toFixed(3) + '\nScore: ' + (node.mrr > 0.7 ? 'Strong' : node.mrr > 0.4 ? 'Moderate' : 'Weak');
      document.getElementById('panel').classList.add('open');
      return true;
    }
    return false;
  };
})();
