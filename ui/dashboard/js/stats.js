// Cortex Memory Dashboard — Stats Bar + Connection Status
// Updates bottom bar stats, KPI strip, status indicator.

(function() {

  function updateStats(data) {
    var s = data.stats;

    // Bottom bar stats
    var bar = document.getElementById('stats-bar');
    bar.innerHTML =
      'Nodes: <span>' + (s.total + s.entities) + '</span> \u00b7 ' +
      'Edges: <span>' + s.relationships + '</span> \u00b7 ' +
      'Heat: <span>' + s.avg_heat.toFixed(3) + '</span>' +
      '<span class="sync-badge">Synchronized</span>';
  }

  function updateConnection() {
    var dot = document.getElementById('status-dot');
    var text = document.getElementById('status-text');
    if (dot) {
      dot.className = 'status-dot ' + (JMD.state.connected ? 'live' : 'dead');
    }
    if (text) {
      text.textContent = JMD.state.connected ? 'Online' : 'Offline';
    }
  }

  JMD.on('data:refresh', updateStats);
  JMD.on('state:connected', updateConnection);
})();
