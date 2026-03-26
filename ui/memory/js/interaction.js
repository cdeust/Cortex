// Cortex Memory Dashboard — Interaction
(function() {
  var CMD = window.CMD;

  CMD.showTooltip = function(n, x, y) {
    var el = document.getElementById('tooltip-brain');
    el.querySelector('.tt-name').textContent = n.name || n.id;
    el.querySelector('.tt-type').textContent = (n.nodeType || '').toUpperCase().replace(/-/g, ' ');
    el.querySelector('.tt-proj').textContent = CMD.cleanProject(n.project);
    el.style.display = 'block';
    var tx = Math.min(x + 14, window.innerWidth - 300);
    var ty = Math.min(y - 10, window.innerHeight - 80);
    el.style.left = tx + 'px';
    el.style.top = ty + 'px';
  };

  CMD.hideTooltip = function() {
    document.getElementById('tooltip-brain').style.display = 'none';
  };

  CMD.initInteraction = function() {
    window.addEventListener('mousemove', function(e) {
      CMD.mouse.x = (e.clientX / CMD.W) * 2 - 1;
      CMD.mouse.y = -(e.clientY / CMD.H) * 2 + 1;
      CMD.mouseScreen = { x: e.clientX, y: e.clientY };
      CMD.renderer.domElement.style.cursor = 'default';
    });

    window.addEventListener('click', function(e) {
      if (e.target.closest('#panel') || e.target.closest('#topbar') ||
          e.target.closest('#filter-row-2-brain') || e.target.closest('#analytics-brain')) return;
      CMD.ray.setFromCamera(CMD.mouse, CMD.camera);
      var hits = CMD.ray.intersectObjects(
        CMD.neuronGroup.children.filter(function(m) { return m.visible; }), false
      );
      if (hits.length) {
        var nd = hits[0].object.userData.node;
        if (nd) { CMD.openPanel(nd); CMD.controls.autoRotate = false; }
      } else if (!e.target.closest('#panel')) {
        CMD.closePanel();
      }
    });

    window.addEventListener('resize', CMD.handleResize);
  };

  CMD.initPanelClose = function() {
    document.getElementById('panel-close').addEventListener('click', CMD.closePanel);
  };
})();
