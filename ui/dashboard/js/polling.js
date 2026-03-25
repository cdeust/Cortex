// Cortex Memory Dashboard — Data Polling
// Fetches /api/dashboard every 3s, updates state on change.

(function() {
  var POLL_INTERVAL = 3000;
  var firstLoad = true;

  function hasStatsChanged(a, b) {
    if (!a || !b) return true;
    return JSON.stringify(a.stats) !== JSON.stringify(b.stats);
  }

  async function poll() {
    try {
      var res = await fetch('/api/dashboard');
      if (!res.ok) throw new Error(res.statusText);
      var data = await res.json();
      var isNew = hasStatsChanged(JMD.state.lastData, data);
      JMD.setState('connected', true);
      JMD.setState('lastData', data);
      if (isNew) JMD.emit('data:refresh', data);

      // Dismiss loading screen on first successful load
      if (firstLoad) {
        firstLoad = false;
        var loading = document.getElementById('loading');
        if (loading) {
          setTimeout(function() {
            loading.classList.add('done');
            // After loading overlay fades, resize renderer to actual container
            setTimeout(function() {
              loading.remove();
              if (JMD.resizeToContainer) JMD.resizeToContainer();
            }, 1100);
          }, 600);
        }
      }
    } catch (e) {
      JMD.setState('connected', false);
    }
  }

  setInterval(poll, POLL_INTERVAL);
  poll();
})();
