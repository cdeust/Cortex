// Cortex Methodology Map — Filters
window.CMV = window.CMV || {};

/**
 * Semantic zoom: adjust node opacity based on camera distance.
 * Hides non-domain nodes when zoomed far out.
 */
CMV.setupZoom = function () {
  var last = null;
  setInterval(function () {
    if (!CMV.graph) return;
    try {
      var d = CMV.graph.camera().position.length();
      if (last && Math.abs(d - last) < 5) return;
      last = d;
      if (!CMV.focused) {
        CMV.graph.nodeOpacity(function (n) {
          if (d > 500 && n.type !== 'domain') return 0.25;
          if (d > 350 && n.type === 'blind-spot') return 0.15;
          return 1;
        });
      }
    } catch (e) { /* camera not ready */ }
  }, 200);
};

/**
 * Set up mouse tracking, window resize, reset button, and close detail events.
 */
CMV.setupEvents = function () {
  var tip = document.getElementById('tooltip');

  addEventListener('mousemove', function (e) {
    CMV.mouse.x = e.clientX;
    CMV.mouse.y = e.clientY;
    if (tip.classList.contains('visible')) {
      var tx = e.clientX + 16, ty = e.clientY + 16;
      if (tx + 240 > innerWidth) tx = e.clientX - 256;
      if (ty + 100 > innerHeight) ty = e.clientY - 116;
      tip.style.left = tx + 'px';
      tip.style.top = ty + 'px';
    }
  });

  addEventListener('resize', function () {
    if (CMV.graph) CMV.graph.width(innerWidth).height(innerHeight);
  });

  document.getElementById('reset-btn').addEventListener('click', function () {
    CMV.closeDetail();
    if (CMV.graph) CMV.graph.cameraPosition({ x: 0, y: 0, z: 500 }, { x: 0, y: 0, z: 0 }, 1200);
  });

  document.getElementById('close-detail').addEventListener('click', CMV.closeDetail);
};
