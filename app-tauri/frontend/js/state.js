// Cortex Neural Graph — Reactive State
(function() {
  var listeners = {};

  JUG.on = function(event, fn) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(fn);
  };

  JUG.emit = function(event, data) {
    (listeners[event] || []).forEach(function(fn) { fn(data); });
  };

  var _state = {
    activeFilter: 'all',
    searchQuery: '',
    selectedId: null,
    zoomLevel: 'L0',
    lastData: null,
    activeView: 'knowledge',
    domainFilter: '',
    emotionFilter: '',
    stageFilter: '',
  };

  JUG.state = {};

  function defineProp(key) {
    Object.defineProperty(JUG.state, key, {
      get: function() { return _state[key]; },
      set: function(v) {
        var old = _state[key];
        _state[key] = v;
        if (old !== v) JUG.emit('state:' + key, { value: v, old: old });
      },
    });
  }

  var keys = Object.keys(_state);
  for (var i = 0; i < keys.length; i++) defineProp(keys[i]);
})();
