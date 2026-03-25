// Cortex Neural Graph — Configuration
var JUG = window.JUG || {};
window.JUG = JUG;

JUG.API_URL = '/api/graph';

JUG.NODE_COLORS = {
  'domain': '#6366f1',
  'entry-point': '#00d4ff',
  'recurring-pattern': '#10b981',
  'tool-preference': '#f59e0b',
  'behavioral-feature': '#a855f7',
  'memory-episodic': '#26de81',
  'memory-semantic': '#d946ef',
  'entity-function': '#00d2ff',
  'entity-dependency': '#3b82f6',
  'entity-error': '#ff4444',
  'entity-decision': '#ffaa00',
  'entity-technology': '#8b5cf6',
  'entity-file': '#6366f1',
  'entity-variable': '#06b6d4',
  'entity-default': '#00d2ff',
};

JUG.EDGE_COLORS = {
  'bridge': '#FF00FF',
  'persistent-feature': '#ec4899',
  'co_occurrence': '#d946ef',
  'imports': '#3b82f6',
  'calls': '#22d3ee',
  'caused_by': '#ff4444',
  'resolved_by': '#22c55e',
  'decided_to_use': '#f59e0b',
  'debugged_with': '#ef4444',
  'has-entry': '#00d4ff',
  'has-pattern': '#10b981',
  'uses-tool': '#f59e0b',
  'has-feature': '#a855f7',
  'memory-entity': '#556677',
  'domain-entity': '#4488aa',
  'default': '#90a4ae',
};

JUG.NODE_LABELS = {
  'domain': 'Domain',
  'entry-point': 'Entry Point',
  'recurring-pattern': 'Pattern',
  'tool-preference': 'Tool',
  'behavioral-feature': 'Feature',
  'memory': 'Memory',
  'entity': 'Entity',
};

JUG.ZOOM_LEVELS = {
  L2: { minDist: 800, label: 'Galaxy' },
  L1: { minDist: 200, label: 'Constellation' },
  L0: { minDist: 0, label: 'Neural' },
};

JUG.getNodeColor = function(node) {
  if (node.type === 'memory') {
    return JUG.NODE_COLORS['memory-' + (node.storeType || 'episodic')] || '#26de81';
  }
  if (node.type === 'entity') {
    return JUG.NODE_COLORS['entity-' + (node.entityType || 'default')] || '#00d2ff';
  }
  return node.color || JUG.NODE_COLORS[node.type] || '#00d2ff';
};

JUG.getEdgeColor = function(edge) {
  return edge.color || JUG.EDGE_COLORS[edge.type] || JUG.EDGE_COLORS['default'];
};
