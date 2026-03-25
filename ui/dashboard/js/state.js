// Cortex Memory Dashboard — State Management
// Centralized reactive state with observer pattern.

(function() {
  window.JMD = window.JMD || {};

  var listeners = {};

  JMD.state = {
    lastData: null,
    connected: false,
    activeView: 'graph',       // graph | timeline | categories
    activeFilter: 'all',       // all | episodic | semantic
    searchQuery: '',
    analyticsOpen: false,
  };

  JMD.on = function(event, fn) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(fn);
  };

  JMD.emit = function(event, data) {
    (listeners[event] || []).forEach(function(fn) { fn(data); });
  };

  JMD.setState = function(key, value) {
    var prev = JMD.state[key];
    if (prev === value) return;
    JMD.state[key] = value;
    JMD.emit('state:' + key, { key: key, value: value, prev: prev });
    JMD.emit('state:change', { key: key, value: value, prev: prev });
  };
})();
