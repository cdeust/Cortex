// Cortex Methodology Map — State
window.CMV = window.CMV || {};

CMV.graphData = null;
CMV.graph = null;
CMV.selectedId = null;
CMV.focused = false;
CMV.mouse = { x: 0, y: 0 };

/* ═══ Clock ═══ */
setInterval(function () {
  var d = new Date();
  var el = document.getElementById('status-time');
  if (el) {
    el.textContent = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function (v) { return String(v).padStart(2, '0'); })
      .join(':');
  }
}, 1000);
