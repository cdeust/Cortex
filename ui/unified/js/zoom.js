// Cortex Neural Graph — Semantic Zoom
(function() {
  var currentLevel = 'L0';

  function checkZoomLevel() {
    var dist = JUG.camera.position.distanceTo(JUG.controls.target);
    var newLevel;

    if (dist > 800) newLevel = 'L2';
    else if (dist > 200) newLevel = 'L1';
    else newLevel = 'L0';

    if (newLevel !== currentLevel) {
      currentLevel = newLevel;
      JUG.state.zoomLevel = newLevel;
      applyZoomLevel(newLevel);
    }
  }

  function applyZoomLevel(level) {
    JUG.allNodes.forEach(function(n) {
      var type = n.type;
      var visible = true;
      var opacity = 1.0;

      if (level === 'L2') {
        // Galaxy: only domains + bridges visible
        if (type !== 'domain') {
          visible = false;
          opacity = 0;
        }
      } else if (level === 'L1') {
        // Constellation: domains + entities + methodology
        if (type === 'memory') {
          opacity = 0.15;
        }
      }

      n.group.visible = visible;
      if (visible && JUG.state.selectedId === null) {
        JUG.setGroupOpacity(n.group, opacity);
      }
    });

    JUG.updateClusterVisibility(level);

    // Update status
    var statusText = document.getElementById('status-zoom');
    if (statusText) statusText.textContent = level;
  }

  JUG.checkZoomLevel = checkZoomLevel;
})();
