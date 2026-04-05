// Cortex Neural Graph — Detail Panel Formatting
// Cleans raw data into human-readable presentation
// Uses JUG._tools (detail_tools.js) for tool capture cards
(function() {

  function cleanLabel(raw) {
    if (!raw) return '';
    var s = raw
      .replace(/^#+\s*/g, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/\s+/g, ' ').trim();
    // Apply tool label cleaning for human-readable titles
    if (JUG._cleanToolLabel) s = JUG._cleanToolLabel(s);
    return s.length > 120 ? s.substring(0, 117) + '...' : s;
  }

  function colorForPct(pct) {
    return pct >= 70 ? '#40D870' : pct >= 40 ? '#E0B040' : '#E07070';
  }

  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }

  // ── Header ──

  function buildHeader(data, col, typeLabel) {
    var h = '<div class="node-badge" style="background:' + col +
      '10;border-color:' + col + '40;color:' + col + '">' +
      '<span style="width:5px;height:5px;border-radius:50%;background:' +
      col + ';display:inline-block;box-shadow:0 0 6px ' + col +
      '"></span> ' + esc(typeLabel) + '</div>';
    h += '<h2>' + esc(bestTitle(data)) + '</h2>';
    if (data.domain) h += '<div class="domain-label">' + esc(data.domain) + '</div>';
    return h;
  }

  function bestTitle(data) {
    var label = cleanLabel(data.label || '');
    // If label looks good, use it
    if (label && label.length > 5 && !label.endsWith('...')) return label;
    // Try deriving a better title from content
    var content = data.content || '';
    if (content) {
      var title = cleanLabel(content);
      if (title && title.length > 3) return title;
    }
    return label || data.id || '';
  }

  // ── Quality ──

  function buildQuality(data) {
    if (data.quality === undefined) return '';
    var pct = Math.round(data.quality * 100);
    var color = colorForPct(pct);
    var word = pct >= 70 ? 'Strong' : pct >= 50 ? 'Good' : pct >= 30 ? 'Fair' : 'Weak';
    return '<div class="section-title">Signal Strength</div>' +
      '<div class="quality-summary">' +
      '<div class="quality-ring" style="--q-pct:' + pct + '%;--q-color:' + color +
      '"><span class="quality-num">' + pct + '</span><span class="quality-pct">%</span></div>' +
      '<div class="quality-info"><div class="quality-word" style="color:' + color +
      '">' + word + ' signal</div><div class="quality-hint">' +
      qualityHint(data) + '</div></div></div>';
  }

  function qualityHint(d) {
    if (d.type === 'memory') {
      var a = d.accessCount > 0 ? 'accessed ' + d.accessCount + 'x' : 'not yet accessed';
      var h = d.heat > 0.7 ? 'actively recalled' : d.heat > 0.3 ? 'moderately active' : 'cooling down';
      return a + ' · ' + h;
    }
    if (d.type === 'domain') return d.sessionCount + ' sessions analyzed';
    if (d.type === 'entity') return 'extracted from memories';
    return '';
  }

  // ── Gauges ──

  function gauge(label, value, max, color, unit) {
    var pct = Math.min(100, Math.round((value / max) * 100));
    var desc = pct >= 70 ? 'High' : pct >= 40 ? 'Medium' : 'Low';
    return '<div class="gauge-row"><div class="gauge-header"><span class="gauge-label">' +
      label + '</span><span class="gauge-val" style="color:' + color + '">' +
      (unit === '%' ? pct + '%' : value) + '</span></div>' +
      '<div class="gauge-track"><div class="gauge-fill" style="width:' + pct +
      '%;background:' + color + '"></div></div><div class="gauge-desc">' + desc + '</div></div>';
  }

  function buildGauges(data) {
    var g = [];
    if (data.heat !== undefined) g.push(gauge('Activity', data.heat, 1, colorForPct(Math.round(data.heat * 100)), '%'));
    if (data.importance !== undefined) g.push(gauge('Importance', data.importance, 1, colorForPct(Math.round(data.importance * 100)), '%'));
    if (data.confidence !== undefined) g.push(gauge('Confidence', data.confidence, 1, colorForPct(Math.round(data.confidence * 100)), '%'));
    if (data.frequency !== undefined) g.push(gauge('Frequency', data.frequency, Math.max(data.frequency, 10), '#50D0E8', 'x'));
    if (data.ratio !== undefined) g.push(gauge('Usage', data.ratio, 1, '#E0A840', '%'));
    if (data.sessionCount !== undefined) g.push(gauge('Sessions', data.sessionCount, Math.max(data.sessionCount, 20), '#50D0E8', 'n'));
    if (!g.length) return '';
    return '<div class="section-title">Metrics</div><div class="gauge-grid">' + g.join('') + '</div>';
  }

  // ── Content ──

  function buildContent(data) {
    if (!data.content) return '';
    if (JUG._tools && JUG._tools.isToolCapture(data.content)) {
      return JUG._tools.renderToolCard(data.content, esc);
    }
    return buildPlainContent(data.content, data.type);
  }

  function buildPlainContent(raw, type) {
    var summary = extractSummary(raw);
    if (!summary) return '';
    var labels = {
      'memory': 'What was remembered', 'entity': 'Description',
      'recurring-pattern': 'Pattern', 'entry-point': 'Entry pattern',
      'domain': 'Summary',
    };
    var h = '<div class="section-title">' + (labels[type] || 'Details') + '</div>';
    h += '<div class="detail-summary">' + esc(summary) + '</div>';
    h += '<div class="detail-raw-toggle" id="detail-raw-btn">Show raw</div>';
    h += '<pre class="detail-raw hidden" id="detail-raw-text">' + esc(raw) + '</pre>';
    return h;
  }

  function extractSummary(raw) {
    // Strip all markup to get clean prose
    var s = raw
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`([^`]*)`/g, '$1')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
      .replace(/^#{1,6}\s*/gm, '')
      .replace(/\*\*([^*]*)\*\*/g, '$1')
      .replace(/\*([^*]*)\*/g, '$1')
      .replace(/^[\s|:*-]+$/gm, '')
      .replace(/<[^>]{0,500}>/g, '')
      .replace(/\\u[0-9a-fA-F]{4}/g, '')
      .replace(/\\n/g, '\n').replace(/\\t/g, '  ')
      .replace(/\n{3,}/g, '\n\n').trim();
    // Take first meaningful paragraph (up to 300 chars)
    var lines = s.split('\n').filter(function(l) { return l.trim().length > 0; });
    var out = '';
    for (var i = 0; i < lines.length && out.length < 300; i++) {
      out += (out ? '\n' : '') + lines[i].trim();
    }
    return out || s.substring(0, 300);
  }

  // ── Tags ──

  function buildTags(tags) {
    if (!tags || !tags.length) return '';
    var clean = tags.filter(function(t) { return !t.startsWith('hash:') && !t.startsWith('cluster:'); });
    if (!clean.length) return '';
    return '<div class="section-title">Tags</div>' + groupTags(clean);
  }

  function groupTags(tags) {
    var groups = {}, TC = JUG._tagColors;
    tags.forEach(function(t) {
      var idx = t.indexOf(':');
      var pfx = (idx > 0 && idx < 12) ? t.substring(0, idx) : '_plain';
      var val = (idx > 0 && idx < 12) ? t.substring(idx + 1) : t;
      if (!groups[pfx]) groups[pfx] = [];
      groups[pfx].push(val);
    });
    var h = '<div class="tag-groups">';
    Object.keys(groups).sort().forEach(function(k) {
      var s = TC[k] || TC['_default'];
      h += '<div class="tag-group">';
      if (k !== '_plain') h += '<span class="tag-group-label" style="color:' + s.color + '">' + k + '</span>';
      h += '<div class="tag-group-items">';
      groups[k].forEach(function(v) {
        var d = v.length > 50 ? '...' + v.slice(-40) : v;
        h += '<span class="detail-tag" style="color:' + s.color + ';border-color:' + s.border + ';background:' + s.bg + '">' + esc(d) + '</span>';
      });
      h += '</div></div>';
    });
    return h + '</div>';
  }

  // ── Biological State ──

  function buildBioSection(data) {
    if (data.type !== 'memory' || !data.consolidationStage) return '';
    var sc = JUG.CONSOLIDATION_COLORS[data.consolidationStage] || '#50C8E0';
    var sl = JUG.CONSOLIDATION_LABELS[data.consolidationStage] || data.consolidationStage;
    var h = '<div class="section-title">Biological State</div>';
    h += bdg(sl, sc);
    h += '<div class="gauge-grid">';
    var fields = [
      ['encodingStrength', 'Encoding Strength', '#50D0E8'],
      ['separationIndex', 'Pattern Separation', '#70D880'],
      ['interferenceScore', 'Interference', '#E07070'],
      ['schemaMatchScore', 'Schema Match', '#E8B840'],
      ['hippocampalDependency', 'Hippocampal Dep.', '#C070D0'],
      ['plasticity', 'Plasticity', '#2DD4BF'],
      ['stability', 'Stability', '#40D870'],
    ];
    fields.forEach(function(f) {
      var val = data[f[0]];
      if (val !== undefined && val !== null) h += gauge(f[0], val, 1, f[2], '%');
    });
    h += '</div>';
    return h;
  }

  // ── Badges ──

  function buildBadges(data) {
    var b = [];
    if (data.isGlobal) b.push(bdg('Global', '#8B6914'));
    if (data.isProtected) b.push(bdg('Anchored', '#E0B840'));
    if (data.storeType) b.push(bdg(data.storeType, '#40A8C0'));
    return b.length ? '<div class="badge-row">' + b.join('') + '</div>' : '';
  }

  function bdg(text, c) {
    return '<span class="detail-badge" style="color:' + c + ';border-color:' + c + '40;background:' + c + '10">' + text + '</span>';
  }

  // ── Config & exports ──

  JUG._tagColors = {
    'file': { color: '#7088D0', bg: '#7088D010', border: '#7088D030' },
    'symbol': { color: '#B088E0', bg: '#B088E010', border: '#B088E030' },
    'lang': { color: '#2DD4BF', bg: '#2DD4BF10', border: '#2DD4BF30' },
    'error': { color: '#E07070', bg: '#E0707010', border: '#E0707030' },
    'tech': { color: '#9080D0', bg: '#9080D010', border: '#9080D030' },
    'tool': { color: '#E0A840', bg: '#E0A84010', border: '#E0A84030' },
    '_default': { color: '#50C8E0', bg: '#50C8E010', border: '#50C8E030' },
  };

  JUG._fmt = {
    cleanLabel: cleanLabel, header: buildHeader, quality: buildQuality,
    gauges: buildGauges, content: buildContent, tags: buildTags,
    badges: buildBadges, bioSection: buildBioSection, gauge: gauge, esc: esc,
  };
})();
