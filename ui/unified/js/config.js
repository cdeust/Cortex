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
  'discussion': '#F43F5E',
};

JUG.EDGE_COLORS = {
  'has-category': '#B0B0B0',
  'has-project': '#8B5CF6',
  'has-agent': '#2DD4BF',
  'has-group': '#64748B',
  'groups': '#50C8E0',
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
  'has-discussion': '#F43F5E60',
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
  'discussion': 'Discussion',
};

JUG.CONSOLIDATION_COLORS = {
  'labile': '#00D2FF',
  'early_ltp': '#60A0E0',
  'late_ltp': '#40D870',
  'consolidated': '#E8B840',
  'reconsolidating': '#C070D0',
};

JUG.CONSOLIDATION_LABELS = {
  'labile': 'Labile',
  'early_ltp': 'Early LTP',
  'late_ltp': 'Late LTP',
  'consolidated': 'Consolidated',
  'reconsolidating': 'Reconsolidating',
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
  if (node.isGlobal) return '#8B6914';
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

// Clean markdown + tool captures from labels for display
JUG.cleanText = function(raw) {
  if (!raw) return '';
  var s = raw.replace(/^#+\s*/g, '').replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1').replace(/\s+/g, ' ').trim();
  return JUG._cleanToolLabel(s);
};

JUG._cleanToolLabel = function(s) {
  // Extract file path — stop before Output:/Command: or JSON
  var fp = JUG._extractFilePath(s);
  // "Tool: Edit File: /long/path/to/file.py ..." → "Edit file.py"
  if (/^Tool:\s*Edit/i.test(s) && fp) return 'Edit ' + JUG._shortFile(fp);
  // "Tool: Write File: /path ..." → "Write file.py"
  if (/^Tool:\s*Write/i.test(s) && fp) return 'Write ' + JUG._shortFile(fp);
  // "Tool: Read ..." → "Read file.py"
  if (/^Tool:\s*Read/i.test(s) && fp) return 'Read ' + JUG._shortFile(fp);
  // "Tool: Bash Command: cmd" → just the command (short)
  var bashMatch = s.match(/^Tool:\s*Bash\s+Command:\s*(.+?)(?:\s+Output:|$)/i);
  if (bashMatch) { var c = bashMatch[1]; return c.length > 36 ? c.substring(0, 33) + '...' : c; }
  // "Tool: WebSearch ..." → "Web search"
  if (/^Tool:\s*Web/i.test(s)) return 'Web search';
  // "Tool: Grep ..." → "Search files"
  if (/^Tool:\s*Grep/i.test(s)) return 'Search files';
  // "File: path" → short filename
  if (/^File:\s/i.test(s) && fp) return JUG._shortFile(fp);
  return s;
};

JUG._extractFilePath = function(s) {
  // Match absolute path: /foo/bar or C:\foo\bar
  var m = s.match(/["']?(\/[^\s"'{}]+|[A-Za-z]:\\[^\s"'{}]+)/);
  if (m) return m[1].replace(/["']$/g, '');
  // Match relative path with extension: foo/bar.py, src/thing.ts
  var rel = s.match(/(?:File:\s*)?([\w./-]+\/[\w./-]+\.\w{1,10})/);
  if (rel) return rel[1];
  return '';
};

// Best label for canvas — uses content for tool captures (label is often truncated)
JUG._bestNodeLabel = function(node) {
  var label = JUG.cleanText(node.label || '');
  // If cleanText produced a good short label, use it
  if (label && !label.endsWith('...') && label.length > 3) return label;
  // Try content field (has full text for tool captures)
  if (node.content) {
    var fromContent = JUG.cleanText(node.content);
    if (fromContent && fromContent.length > 3) return fromContent;
  }
  return label || node.id || '';
};

JUG._shortFile = function(path) {
  if (!path) return '';
  var clean = path.replace(/^["']|["']$/g, '').trim();
  var parts = clean.split('/').filter(function(p) { return p; });
  if (parts.length <= 1) return clean;
  return parts[parts.length - 1];
};
