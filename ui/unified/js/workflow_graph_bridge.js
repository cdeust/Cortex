// Cortex — Workflow Graph bridge.
// Detects workflow-graph-shaped data (nodes with `kind` in the new schema)
// and takes over the "graph" tab — hides every child of #graph-container
// except our wrapper, disables the legacy force-graph animation, renders
// via JUG.renderWorkflowGraph. Falls back to the legacy renderer for old
// (type-based) payloads.
(function () {
  var LOG = '[wfg]';
  var WFG_KINDS = {
    domain: 1, skill: 1, command: 1, hook: 1, agent: 1,
    tool_hub: 1, file: 1, memory: 1, discussion: 1, entity: 1,
  };
  var _handle = null;
  var _wrapperId = 'wfg-container';
  var _lastPayload = null;

  function isWorkflowGraph(data) {
    if (!data || !Array.isArray(data.nodes) || data.nodes.length === 0) return false;
    if (data.meta && data.meta.schema === 'workflow_graph.v1') return true;
    for (var i = 0; i < Math.min(data.nodes.length, 50); i++) {
      var k = data.nodes[i].kind;
      if (k && WFG_KINDS[k]) return true;
    }
    return false;
  }

  function ensureWrapper() {
    var host = document.getElementById('graph-container');
    if (!host) return null;
    var wrapper = document.getElementById(_wrapperId);
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.id = _wrapperId;
      wrapper.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:5;';
      host.appendChild(wrapper);
    }
    return wrapper;
  }

  function hideLegacyRenderer() {
    var host = document.getElementById('graph-container');
    if (!host) return;
    var kids = host.childNodes;
    for (var i = 0; i < kids.length; i++) {
      var node = kids[i];
      if (node.nodeType !== 1) continue;
      if (node.id === _wrapperId) continue;
      if (node.classList && node.classList.contains('wfg-panel')) continue;
      node.style.display = 'none';
    }
    if (window.JUG && typeof JUG.getGraph === 'function') {
      var g = JUG.getGraph();
      if (g && typeof g.pauseAnimation === 'function') {
        try { g.pauseAnimation(); } catch (_) {}
      }
    }
  }

  function render(data) {
    try {
      var wrapper = ensureWrapper();
      if (!wrapper) { console.warn(LOG, 'no #graph-container'); return false; }
      hideLegacyRenderer();
      if (_handle && typeof _handle.destroy === 'function') {
        try { _handle.destroy(); } catch (_) {}
      }
      if (!window.JUG || typeof JUG.renderWorkflowGraph !== 'function') {
        console.warn(LOG, 'renderWorkflowGraph missing — retry in 80ms');
        setTimeout(function () { render(data); }, 80);
        return false;
      }
      _handle = JUG.renderWorkflowGraph(wrapper, data);
      _lastPayload = data;
      console.log(LOG, 'rendered', (data.nodes || []).length, 'nodes /',
                  (data.edges || data.links || []).length, 'edges');
      return true;
    } catch (err) {
      console.error(LOG, 'render failed', err);
      return false;
    }
  }

  function attach() {
    if (!window.JUG || !JUG.on) { setTimeout(attach, 50); return; }
    console.log(LOG, 'bridge attached');
    JUG.on('state:lastData', function (ev) {
      var data = ev && ev.value;
      if (isWorkflowGraph(data)) render(data);
    });
    if (JUG.state && isWorkflowGraph(JUG.state.lastData)) render(JUG.state.lastData);

    JUG.on('state:activeView', function (ev) {
      if (ev && ev.value === 'graph') {
        var w = document.getElementById(_wrapperId);
        if (w) w.style.display = 'block';
        hideLegacyRenderer();
        if (_lastPayload == null && JUG.state && isWorkflowGraph(JUG.state.lastData)) {
          render(JUG.state.lastData);
        } else if (_handle && typeof _handle.reflow === 'function') {
          setTimeout(function () { _handle.reflow(); }, 60);
        }
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }

  window.JUG = window.JUG || {};
  window.JUG.renderWorkflowGraphIntoTab = render;
  window.JUG.isWorkflowGraph = isWorkflowGraph;
})();
