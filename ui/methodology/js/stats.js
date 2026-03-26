// Cortex Methodology Map — Stats
window.CMV = window.CMV || {};

/**
 * Update the HUD info panel stat counters from graph data.
 * @param {Object} d - Filtered graph data with nodes and edges arrays.
 */
CMV.updateStats = function (d) {
  var c = {};
  d.nodes.forEach(function (n) {
    c[n.type] = (c[n.type] || 0) + 1;
  });
  document.getElementById('s-dom').textContent  = c['domain'] || 0;
  document.getElementById('s-ent').textContent  = c['entry-point'] || 0;
  document.getElementById('s-pat').textContent  = c['recurring-pattern'] || 0;
  document.getElementById('s-tool').textContent = c['tool-preference'] || 0;
  document.getElementById('s-bs').textContent   = c['blind-spot'] || 0;
  document.getElementById('s-edge').textContent = d.edges.length;
};
