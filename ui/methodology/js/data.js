// Cortex Methodology Map — Data
window.CMV = window.CMV || {};

/**
 * Fetch graph data from server, falling back to sample data.
 * @returns {Promise<Object>} Raw graph data with nodes, edges, blindSpotRegions.
 */
CMV.loadData = async function () {
  try {
    var res = await fetch(CMV.SERVER_URL, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (e) {
    console.warn('[cortex] Fallback sample data:', e.message);
    return CMV.SAMPLE;
  }
};

/**
 * Filter raw data to top 12 domains by session count.
 * Prevents the 1582-node blob by capping children per type per domain.
 * @param {Object} raw - Raw graph data.
 * @returns {Object} Filtered graph data.
 */
CMV.filterData = function (raw) {
  var nodes = raw.nodes || [];
  var edges = raw.edges || [];
  var bs = raw.blindSpotRegions || [];

  var MAX_DOMAINS = 12;
  var domainNodes = nodes
    .filter(function (n) { return n.type === 'domain'; })
    .sort(function (a, b) { return (b.sessionCount || 0) - (a.sessionCount || 0); })
    .slice(0, MAX_DOMAINS);
  var keepDomains = new Set(domainNodes.map(function (n) { return n.domain; }));
  var keepDomainIds = new Set(domainNodes.map(function (n) { return n.id; }));

  var MAX_ENTRIES = 3, MAX_PATTERNS = 5, MAX_TOOLS = 4;
  var countPerDomain = {};
  var filteredNodes = domainNodes.slice();

  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (n.type === 'domain') continue;
    if (!keepDomains.has(n.domain)) continue;
    var key = n.domain + ':' + n.type;
    countPerDomain[key] = (countPerDomain[key] || 0) + 1;
    var limit = n.type === 'entry-point' ? MAX_ENTRIES
              : n.type === 'recurring-pattern' ? MAX_PATTERNS
              : n.type === 'tool-preference' ? MAX_TOOLS : 3;
    if (countPerDomain[key] <= limit) filteredNodes.push(n);
  }

  var keepIds = new Set(filteredNodes.map(function (n) { return n.id; }));
  var filteredEdges = edges.filter(function (e) {
    var s = typeof e.source === 'object' ? e.source.id : e.source;
    var t = typeof e.target === 'object' ? e.target.id : e.target;
    return keepIds.has(s) && keepIds.has(t);
  });

  var bsCount = {};
  var bsNodes = [];
  var bsEdges = [];
  for (var j = 0; j < bs.length; j++) {
    var b = bs[j];
    if (!keepDomains.has(b.domain)) continue;
    bsCount[b.domain] = (bsCount[b.domain] || 0) + 1;
    if (bsCount[b.domain] > 2) continue;
    var id = 'bs_' + bsNodes.length;
    bsNodes.push({
      id: id, type: 'blind-spot', label: b.value, domain: b.domain,
      confidence: 0.1, severity: b.severity,
      description: b.description, suggestion: b.suggestion,
      color: '#333344', size: 3, _bs: true,
    });
    var hub = domainNodes.find(function (dn) { return dn.domain === b.domain; });
    if (hub) bsEdges.push({ source: hub.id, target: id, type: 'has-blindspot', weight: 0.08 });
  }

  return {
    nodes: filteredNodes.concat(bsNodes),
    edges: filteredEdges.concat(bsEdges),
    blindSpotRegions: bs.filter(function (b) { return keepDomains.has(b.domain); }),
  };
};
