// Cortex Memory Dashboard — Configuration & Constants
// Single source of truth for colors, sizes, and type definitions.

(function() {
  window.JMD = window.JMD || {};

  JMD.TYPE_COLORS = {
    episodic: 0x26de81,
    semantic: 0xd946ef,
    entity:   0x00d2ff,
  };

  JMD.CATEGORY_DEFS = {
    decision:     { icon: '!', color: '#ffaa00', bg: '#451a03', keywords: ['decision', 'decided'] },
    architecture: { icon: '#', color: '#3b82f6', bg: '#172554', keywords: ['architecture'] },
    error:        { icon: 'x', color: '#ff4444', bg: '#450a0a', keywords: ['error', 'typeerror', 'fix'] },
    session:      { icon: '>', color: '#8b5cf6', bg: '#3b0764', keywords: ['session-summary'] },
    knowledge:    { icon: '*', color: '#00d2ff', bg: '#164e63', keywords: [] },
    other:        { icon: '.', color: '#5a7a9a', bg: '#1e293b', keywords: [] },
  };

  // Agent topic colors for team memory visualization
  JMD.AGENT_COLORS = {
    engineer:     '#8b5cf6',
    tester:       '#10b981',
    reviewer:     '#f59e0b',
    architect:    '#3b82f6',
    dba:          '#06b6d4',
    researcher:   '#ef4444',
    frontend:     '#ec4899',
    security:     '#f97316',
    devops:       '#14b8a6',
    ux:           '#a855f7',
    orchestrator: '#6366f1',
  };

  JMD.agentColor = function(agent) {
    return JMD.AGENT_COLORS[agent] || '#5a7a9a';
  };

  JMD.HEAT_COLORS = {
    hot:  '#ff4444',
    warm: '#ffaa00',
    cool: '#00d2ff',
    cold: '#3a6a9a',
  };

  JMD.heatColorCSS = function(h) {
    if (h > 0.7) return JMD.HEAT_COLORS.hot;
    if (h > 0.5) return JMD.HEAT_COLORS.warm;
    if (h > 0.3) return JMD.HEAT_COLORS.cool;
    return JMD.HEAT_COLORS.cold;
  };

  JMD.categorizeMemory = function(m) {
    var c = (m.content || '').toLowerCase();
    var tags = (m.tags || []).map(function(t) { return t.toLowerCase(); });

    for (var cat in JMD.CATEGORY_DEFS) {
      if (cat === 'knowledge' || cat === 'other') continue;
      var def = JMD.CATEGORY_DEFS[cat];
      for (var k = 0; k < def.keywords.length; k++) {
        if (tags.indexOf(def.keywords[k]) >= 0 || c.indexOf(def.keywords[k]) >= 0) return cat;
      }
    }
    if (m.store_type === 'semantic') return 'knowledge';
    return 'other';
  };

  JMD.timeAgo = function(iso) {
    if (!iso) return '\u2014';
    var s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  };

  JMD.escHtml = function(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };
})();
