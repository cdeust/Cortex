// Cortex Neural Graph — Configuration
var JUG = window.JUG || {};
window.JUG = JUG;

JUG.API_URL = '/api/graph';

JUG.NODE_COLORS = {
  'root': '#FFFFFF',
  'category': '#8B5CF6',
  'domain': '#E8B840',
  'agent': '#2DD4BF',
  'type-group': '#64748B',
  'entry-point': '#60D8F0',
  'recurring-pattern': '#70D880',
  'tool-preference': '#E0A840',
  'behavioral-feature': '#B088E0',
  'memory-episodic': '#58D888',
  'memory-semantic': '#C070D0',
  'entity-function': '#50D0E8',
  'entity-dependency': '#60A0E0',
  'entity-error': '#E07070',
  'entity-decision': '#E0C050',
  'entity-technology': '#9080D0',
  'entity-file': '#7088D0',
  'entity-variable': '#50B8D0',
  'entity-default': '#50C8E0',
};

JUG.EDGE_COLORS = {
  'has-category': '#FFFFFF30',
  'has-project': '#8B5CF640',
  'has-agent': '#2DD4BF40',
  'has-group': '#64748B40',
  'groups': '#50C8E030',
  'bridge': '#C080D0',
  'persistent-feature': '#B070B8',
  'co_occurrence': '#9080C0',
  'imports': '#60A0D0',
  'calls': '#60C0D0',
  'caused_by': '#D07070',
  'resolved_by': '#60C080',
  'decided_to_use': '#D0B060',
  'debugged_with': '#D07060',
  'memory-entity': '#40A0B8',
  'domain-entity': '#50B0C8',
  'default': '#40B0C8',
};

JUG.NODE_LABELS = {
  'root': 'Cortex',
  'category': 'Category',
  'domain': 'Project',
  'agent': 'Agent',
  'type-group': 'Group',
  'entry-point': 'Entry Point',
  'recurring-pattern': 'Pattern',
  'tool-preference': 'Tool',
  'behavioral-feature': 'Feature',
  'memory': 'Memory',
  'entity': 'Entity',
};

JUG.ZOOM_LEVELS = {
  L3: { minDist: 1200, label: 'Universe' },
  L2: { minDist: 600, label: 'Galaxy' },
  L1: { minDist: 200, label: 'Constellation' },
  L0: { minDist: 0, label: 'Neural' },
};

// Structural types that form the tree skeleton
JUG.STRUCTURAL_TYPES = { 'root': true, 'category': true, 'domain': true, 'agent': true, 'type-group': true };

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
