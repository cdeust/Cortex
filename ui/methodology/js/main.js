// Cortex Methodology Map — Main
window.CMV = window.CMV || {};

/**
 * Boot sequence: load data, build graph, set up scene and interactions.
 */
CMV.boot = async function () {
  var raw = await CMV.loadData();
  var data = CMV.filterData(raw);
  CMV.build(data);
  CMV.setupScene();
  CMV.setupZoom();
  CMV.setupEvents();

  var domainCount = data.nodes.filter(function (n) { return n.type === 'domain'; }).length;
  document.getElementById('status-text').textContent = domainCount + ' domains online';

  setTimeout(function () {
    document.getElementById('loading').classList.add('done');
    setTimeout(function () {
      document.getElementById('loading').remove();
    }, 1100);
  }, 1000);
};

CMV.boot();
