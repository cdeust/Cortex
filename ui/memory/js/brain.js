// Cortex Memory Dashboard — Brain Geometry
(function() {
  var CMD = window.CMD;

  // Brain volume dimensions
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

  CMD.buildBrainShell = function() {
    var d = CMD.brainDims();
    var brainGeo = new THREE.IcosahedronGeometry(1, 5);
    var pos = brainGeo.attributes.position;

    for (var i = 0; i < pos.count; i++) {
      var x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      var len = Math.sqrt(x * x + y * y + z * z) || 1;
      x /= len; y /= len; z /= len;

      var sx = d.RX, sy = d.RY * 0.85, sz = d.RZ * 0.9;
      var fissure = 1.0 - 0.12 * Math.exp(-x * x * 18);
      var temporal = 1.0 + 0.08 * Math.max(0, -y * 0.7) * (1 - Math.abs(x) * 0.3);
      var frontal = 1.0 + 0.06 * Math.max(0, z * 0.8) * (1 - Math.abs(y) * 0.5);
      var cerebellum = 1.0 + 0.1 * Math.max(0, -z * 0.8) * Math.max(0, -y * 0.6);

      var freq1 = 3.5, freq2 = 7.0, freq3 = 14.0;
      var n = CMD.noise3D(x * freq1, y * freq1, z * freq1) * 0.06
            + CMD.noise3D(x * freq2, y * freq2, z * freq2) * 0.03
            + CMD.noise3D(x * freq3, y * freq3, z * freq3) * 0.015;

      var shape = fissure * temporal * frontal * cerebellum;
      var r = (1.0 + n) * shape;
      pos.setXYZ(i, x * sx * r, y * sy * r, z * sz * r);
    }
    brainGeo.computeVertexNormals();

    var shellMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { uColor: { value: new THREE.Color(0x88bbdd) }, uTime: { value: 0 } },
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
        '  float alpha = edge * 0.12 + 0.015;' +
        '  vec3 col = uColor * (0.6 + edge * 0.8);' +
        '  col += uColor * 0.05 * sin(gl_FragCoord.x*0.01 + gl_FragCoord.y*0.01 + uTime*0.5);' +
        '  gl_FragColor = vec4(col, alpha);' +
        '}',
    });
    var brainShell = new THREE.Mesh(brainGeo, shellMat);
    brainShell.name = 'brainShell';
    CMD.scene.add(brainShell);

    window._brainShellMat = shellMat;
    CMD.GLOW_TEX = CMD.makeGlowTex(64);
  };
})();
