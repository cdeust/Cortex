// Cortex Memory Dashboard — Brain Geometry (per-project shells)
(function() {
  var CMD = window.CMD;

  // Domain-specific colors for brain shells
  var DOMAIN_COLORS = [
    0x88bbdd, // default cyan-blue
    0xdd88aa, // rose
    0x88ddaa, // mint
    0xddbb88, // amber
    0xaa88dd, // violet
    0x88dddd, // teal
    0xdd8888, // coral
    0xbbdd88, // lime
  ];

  CMD.brainDims = function() {
    var S = CMD.brainScale;
    return {
      HX: 38 * S, RX: 162 * S, RY: 118 * S, RZ: 140 * S
    };
  };

  CMD.inBrain = function(x, y, z) {
    var S = CMD.brainScale;
    var d = CMD.brainDims();
    if (y > 118 * S || y < -108 * S) return false;
    var tp = y < -42 * S ? Math.max(0.28, 1 - (-y - 42 * S) / (80 * S) * 0.65) : 1;
    var d1 = ((x + d.HX) / (d.RX * tp)) ** 2 + (y / d.RY) ** 2 + (z / (d.RZ * tp)) ** 2;
    var d2 = ((x - d.HX) / (d.RX * tp)) ** 2 + (y / d.RY) ** 2 + (z / (d.RZ * tp)) ** 2;
    return Math.min(d1, d2) <= 1;
  };

  CMD.clamp = function(x, y, z) {
    if (CMD.inBrain(x, y, z)) return [x, y, z];
    var s = 0.9;
    while (!CMD.inBrain(x * s, y * s, z * s) && s > 0.05) s -= 0.04;
    return [x * s, y * s, z * s];
  };

  CMD.noise3D = function(x, y, z) {
    var X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
    var xf = x - Math.floor(x), yf = y - Math.floor(y), zf = z - Math.floor(z);
    var u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf);
    function h(i, j, k) { return Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453 % 1; }
    var a = h(X, Y, Z), b = h(X + 1, Y, Z), c = h(X, Y + 1, Z), d = h(X + 1, Y + 1, Z);
    var e = h(X, Y, Z + 1), f = h(X + 1, Y, Z + 1), g2 = h(X, Y + 1, Z + 1), i = h(X + 1, Y + 1, Z + 1);
    var x1 = a + (b - a) * u, x2 = c + (d - c) * u, x3 = e + (f - e) * u, x4 = g2 + (i - g2) * u;
    return (x1 + (x2 - x1) * v) + ((x3 + (x4 - x3) * v) - (x1 + (x2 - x1) * v)) * w;
  };

  CMD.makeGlowTex = function(size) {
    var c = document.createElement('canvas');
    c.width = c.height = size;
    var ctx = c.getContext('2d'), h = size / 2;
    var g = ctx.createRadialGradient(h, h, 0, h, h, h);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.2, 'rgba(255,255,255,0.8)');
    g.addColorStop(0.5, 'rgba(255,255,255,0.25)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    return new THREE.CanvasTexture(c);
  };

  function _makeBrainGeo(scale) {
    var geo = new THREE.IcosahedronGeometry(1, 4);
    var pos = geo.attributes.position;
    var rx = 162 * scale, ry = 118 * scale * 0.85, rz = 140 * scale * 0.9;
    var hx = 38 * scale;

    for (var i = 0; i < pos.count; i++) {
      var x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      var len = Math.sqrt(x * x + y * y + z * z) || 1;
      x /= len; y /= len; z /= len;

      var fissure = 1.0 - 0.12 * Math.exp(-x * x * 18);
      var temporal = 1.0 + 0.08 * Math.max(0, -y * 0.7) * (1 - Math.abs(x) * 0.3);
      var frontal = 1.0 + 0.06 * Math.max(0, z * 0.8) * (1 - Math.abs(y) * 0.5);
      var n = CMD.noise3D(x * 3.5, y * 3.5, z * 3.5) * 0.06
            + CMD.noise3D(x * 7, y * 7, z * 7) * 0.03;
      var r = (1.0 + n) * fissure * temporal * frontal;
      pos.setXYZ(i, x * rx * r, y * ry * r, z * rz * r);
    }
    geo.computeVertexNormals();
    return geo;
  }

  function _makeShellMat(color) {
    return new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { uColor: { value: new THREE.Color(color) }, uTime: { value: 0 } },
      vertexShader:
        'varying vec3 vNormal; varying vec3 vViewDir;' +
        'void main(){' +
        '  vNormal = normalize(normalMatrix * normal);' +
        '  vec4 mvPos = modelViewMatrix * vec4(position,1.);' +
        '  vViewDir = normalize(-mvPos.xyz);' +
        '  gl_Position = projectionMatrix * mvPos;' +
        '}',
      fragmentShader:
        'uniform vec3 uColor; uniform float uTime;' +
        'varying vec3 vNormal; varying vec3 vViewDir;' +
        'void main(){' +
        '  float fresnel = 1.0 - abs(dot(vNormal, vViewDir));' +
        '  float edge = pow(fresnel, 2.5);' +
        '  float alpha = edge * 0.14 + 0.02;' +
        '  vec3 col = uColor * (0.6 + edge * 0.8);' +
        '  col += uColor * 0.05 * sin(gl_FragCoord.x*0.01 + gl_FragCoord.y*0.01 + uTime*0.5);' +
        '  gl_FragColor = vec4(col, alpha);' +
        '}',
    });
  }

  function _makeDomainLabel(name, color) {
    var canvas = document.createElement('canvas');
    canvas.width = 512; canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, 512, 64);
    ctx.font = '700 28px Orbitron, "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 8;
    ctx.fillStyle = '#' + new THREE.Color(color).getHexString();
    ctx.fillText(name.toUpperCase(), 256, 32);
    var tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, opacity: 0.85,
      depthWrite: false, sizeAttenuation: true,
    }));
    sprite.scale.set(80, 10, 1);
    return sprite;
  }

  CMD.buildBrainShell = function() {
    CMD.GLOW_TEX = CMD.makeGlowTex(64);
    CMD.brainShells = {};

    var hubs = CMD.hubNs || [];
    if (hubs.length === 0) {
      // Fallback: single brain shell (no project hubs)
      var geo = _makeBrainGeo(CMD.brainScale);
      var mat = _makeShellMat(DOMAIN_COLORS[0]);
      var shell = new THREE.Mesh(geo, mat);
      shell.name = 'brainShell';
      CMD.scene.add(shell);
      window._brainShellMat = mat;
      return;
    }

    // One brain per project hub
    hubs.forEach(function(hub, hi) {
      var color = DOMAIN_COLORS[hi % DOMAIN_COLORS.length];
      var nodeCount = hub.connections || 10;
      // Scale brain size by node count (min 0.3, max 1.0)
      var scale = CMD.brainScale * Math.min(1.0, Math.max(0.3, nodeCount / 200));

      var geo = _makeBrainGeo(scale);
      var mat = _makeShellMat(color);
      var shell = new THREE.Mesh(geo, mat);
      shell.name = 'brainShell_' + hub.project;

      // Position at hub location (set by layout)
      if (hub.bx !== undefined) {
        shell.position.set(hub.bx, hub.by, hub.bz);
      }

      CMD.scene.add(shell);
      CMD.brainShells[hub.project] = { mesh: shell, mat: mat, color: color };

      // Domain label above the brain
      var label = _makeDomainLabel(hub.name, color);
      label.position.set(0, 130 * scale, 0);
      shell.add(label);
    });

    // Use first shell mat for time animation
    var firstKey = Object.keys(CMD.brainShells)[0];
    if (firstKey) window._brainShellMat = CMD.brainShells[firstKey].mat;
  };

  // Update brain positions after layout runs
  CMD.updateBrainPositions = function() {
    if (!CMD.brainShells) return;
    (CMD.hubNs || []).forEach(function(hub) {
      var shell = CMD.brainShells[hub.project];
      if (shell && hub.bx !== undefined) {
        shell.mesh.position.set(hub.bx, hub.by, hub.bz);
      }
    });
  };
})();
