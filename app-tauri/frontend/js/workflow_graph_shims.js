// Cortex — Legacy graph shims.
//
// The legacy ``force-graph`` renderer and its siblings (renderer.js,
// graph.js, draw.js, tooltip.js) have been REMOVED from the page.
// They mounted a canvas inside #graph-container whose GPU compositing
// layer painted a persistent rectangle over the workflow graph.
//
// Some still-loaded scripts (polling.js, detail_panel.js, controls.js,
// monitor.js) reference the JUG API those modules used to install.
// We stub every call as a no-op so the rest of the UI keeps working.
(function () {
  window.JUG = window.JUG || {};
  function noop() {}
  function emptyGraphData() { return { nodes: [], links: [] }; }
  var stubGraph = {
    graphData: emptyGraphData,
    nodeRelSize: noop,
    linkColor: function () { return stubGraph.linkColor; },
    pauseAnimation: noop,
    resumeAnimation: noop,
    zoomToFit: noop,
    centerAt: noop,
  };
  if (!JUG.buildGraph)       JUG.buildGraph = noop;
  if (!JUG.setGraphData)     JUG.setGraphData = noop;
  if (!JUG.addBatchToGraph)  JUG.addBatchToGraph = noop;
  if (!JUG.resetCamera)      JUG.resetCamera = noop;
  if (!JUG.selectNodeById)   JUG.selectNodeById = noop;
  if (!JUG.deselectNode)     JUG.deselectNode = noop;
  if (!JUG.getGraph)         JUG.getGraph = function () { return stubGraph; };
})();
