// Cortex Memory Board — Kanban by consolidation stage with flow header
// Shows consolidated vs dropped memories in a tree-like view
(function() {
  var container = null;
  var visible = false;
  var currentData = null;
  var selectedId = null;
  var _emitting = false;

  var STAGES = ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'];
  var STAGE_COLORS = JUG.CONSOLIDATION_COLORS;
  var STAGE_LABELS = JUG.CONSOLIDATION_LABELS || {};
  var EMO_COLORS = {
    urgency: '#ff3366', frustration: '#ef4444',
    satisfaction: '#22c55e', discovery: '#f59e0b',
    confusion: '#8b5cf6'
  };

  var STAGE_BIO = {
    labile: { decay: '2.0x', vuln: '90%', plast: '100%', advance: 'DA\u22651 or imp>0.3' },
    early_ltp: { decay: '1.2x', vuln: '50%', plast: '70%', advance: 'replay\u22651 or imp>0.4' },
    late_ltp: { decay: '0.8x', vuln: '20%', plast: '30%', advance: 'replay\u22653' },
    consolidated: { decay: '0.5x', vuln: '5%', plast: '10%', advance: 'Stable' },
    reconsolidating: { decay: '1.5x', vuln: '80%', plast: '90%', advance: 'Re-stabilizes' },
  };

  function init() {
    container = document.getElementById('timeline-container');
    if (!container) return;

    JUG.on('state:activeView', function(ev) {
      if (ev.value === 'timeline') show(); else hide();
    });
    JUG.on('state:lastData', function(ev) {
      if (visible && ev.value) { currentData = ev.value; rebuild(); }
    });
    JUG.on('state:activeFilter', rebuildIfVisible);
    JUG.on('state:domainFilter', rebuildIfVisible);
    JUG.on('state:emotionFilter', rebuildIfVisible);
    JUG.on('state:stageFilter', rebuildIfVisible);
    JUG.on('graph:selectNode', function(node) {
      if (_emitting || !visible || !node || node.type !== 'memory') return;
      if (selectedId === node.id) return;
      highlightMemory(node.id);
    });
    JUG.on('graph:deselectNode', function() {
      if (_emitting || !visible) return;
      clearHighlight();
    });
  }

  function show() {
    if (!container) return;
    container.style.display = 'flex';
    visible = true;
    if (JUG.state.lastData) { currentData = JUG.state.lastData; rebuild(); }
    if (JUG.state.selectedId) highlightMemory(JUG.state.selectedId);

    // 30s poll for live updates
    if (!window._boardPollInterval) {
      window._boardPollInterval = setInterval(function() {
        if (document.querySelector('.kb-board')) {
          fetch('/api/graph').then(function(r) { return r.json(); }).then(function(data) {
            JUG._events.emit('data:loaded', data);
          }).catch(function() {});
        }
      }, 30000);
    }
  }
  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
  }
  function rebuildIfVisible() { if (visible && currentData) rebuild(); }

  function extractMemories(data) {
    var nodes = data.nodes ? data.nodes.filter(function(n) {
      return n.type === 'memory';
    }) : [];
    if (JUG._applyExtraFilters) nodes = JUG._applyExtraFilters(nodes);
    nodes.forEach(function(n) { n._ts = parseTs(n.createdAt) || 0; });
    return nodes;
  }

  function parseTs(val) {
    if (!val) return null;
    var d = new Date(val);
    return isNaN(d.getTime()) ? null : d.getTime();
  }

  function rebuild() {
    var memories = extractMemories(currentData);
    container.innerHTML = '';

    // Group by stage
    var groups = {};
    STAGES.forEach(function(s) { groups[s] = []; });
    memories.forEach(function(m) {
      // Accept all shapes the backend has emitted over time:
      //   m.stage                (current workflow_graph.v1 field)
      //   m.consolidationStage   (legacy camelCase)
      //   m.consolidation_stage  (snake_case from memory record)
      var s = m.stage || m.consolidationStage || m.consolidation_stage || 'labile';
      if (!groups[s]) s = 'labile';
      groups[s].push(m);
    });
    STAGES.forEach(function(s) {
      groups[s].sort(function(a, b) {
        return (b.heat || 0) - (a.heat || 0) || (b._ts || 0) - (a._ts || 0);
      });
    });

    var total = memories.length;

    // ── Flow header ──
    var flowStrip = el('div', 'kb-flow-strip');
    STAGES.forEach(function(stage, i) {
      var sc = STAGE_COLORS[stage] || '#50C8E0';
      var count = groups[stage].length;
      var pct = total > 0 ? (count / total * 100) : 0;
      var bio = STAGE_BIO[stage];

      if (i > 0) {
        var arrow = el('div', 'kb-flow-arrow');
        arrow.style.setProperty('--sc', STAGE_COLORS[STAGES[i-1]] || '#50C8E0');
        arrow.innerHTML = '<div class="kb-flow-arrow-line"></div>';
        flowStrip.appendChild(arrow);
      }

      // Compute live metrics
      var stageMems = groups[stage];
      var avgHeat = 0, avgImp = 0, avgEnc = 0, avgInterf = 0, avgReplay = 0, avgHippo = 0;
      if (stageMems.length > 0) {
        stageMems.forEach(function(m) {
          avgHeat += (m.heat || 0);
          avgImp += (m.importance || 0);
          avgEnc += (m.encodingStrength || 0);
          avgInterf += (m.interferenceScore || 0);
          avgReplay += (m.accessCount || 0);
          avgHippo += (m.hippocampalDependency || 0);
        });
        var n = stageMems.length;
        avgHeat /= n; avgImp /= n; avgEnc /= n; avgInterf /= n; avgReplay /= n; avgHippo /= n;
      }

      var card = el('div', 'kb-flow-node');
      card.style.setProperty('--sc', sc);

      // Count + name
      card.innerHTML =
        '<div class="kb-flow-count" style="color:' + sc + '">' + count + '</div>' +
        '<div class="kb-flow-label">' + (STAGE_LABELS[stage] || stage).toUpperCase() + '</div>';

      // Percentage bar
      var pctRow = el('div', 'kb-flow-pct-row');
      pctRow.innerHTML =
        '<div class="kb-flow-pct-bar"><div class="kb-flow-pct-fill" style="width:' + pct + '%;background:' + sc + '"></div></div>' +
        '<span class="kb-flow-pct">' + pct.toFixed(1) + '%</span>';
      card.appendChild(pctRow);

      // Biological properties
      var bioEl = el('div', 'kb-flow-bio-section');
      bioEl.innerHTML =
        '<div class="kb-flow-bio-row"><span>Decay</span><span>' + bio.decay + '</span></div>' +
        '<div class="kb-flow-bio-row"><span>Vulnerability</span><span>' + bio.vuln + '</span></div>' +
        '<div class="kb-flow-bio-row"><span>Plasticity</span><span>' + bio.plast + '</span></div>';
      card.appendChild(bioEl);

      // Live metrics bars
      if (count > 0) {
        var liveEl = el('div', 'kb-flow-live');
        liveEl.innerHTML =
          '<div class="kb-flow-live-title">LIVE</div>' +
          miniBar('Heat', avgHeat, sc) +
          miniBar('Import', avgImp, sc) +
          miniBar('Enc', avgEnc, sc) +
          miniBar('Interf', avgInterf, '#E07070') +
          miniBar('Hippo', avgHippo, '#C070D0') +
          '<div class="kb-flow-bio-row"><span>Replay</span><span>' + avgReplay.toFixed(1) + '</span></div>';
        card.appendChild(liveEl);
      }

      // Advance condition
      var advEl = el('div', 'kb-flow-advance');
      advEl.innerHTML = '<span style="color:' + sc + '">Advance:</span> ' + bio.advance;
      card.appendChild(advEl);

      // At-risk count badge
      var atRisk = stageMems.filter(function(m) {
        return (m.interferenceScore || 0) > 0.3 && (m.heat || 0) < 0.2;
      }).length;
      if (atRisk > 0) {
        var riskBadge = el('div', 'kb-flow-risk-badge');
        riskBadge.textContent = '\u26A0 ' + atRisk + ' at risk';
        card.appendChild(riskBadge);
      }

      flowStrip.appendChild(card);
    });
    container.appendChild(flowStrip);

    // ── Board columns ──
    var board = el('div', 'kb-board');

    STAGES.forEach(function(stage) {
      var sc = STAGE_COLORS[stage] || '#50C8E0';
      var mems = groups[stage];

      var col = el('div', 'kb-col');
      col.style.setProperty('--sc', sc);

      // Header
      var header = el('div', 'kb-col-header');
      var title = el('span', 'kb-col-title');
      title.textContent = (STAGE_LABELS[stage] || stage).toUpperCase();
      header.appendChild(title);
      var count = el('span', 'kb-col-count');
      count.textContent = mems.length;
      header.appendChild(count);
      col.appendChild(header);

      // Cards
      var cards = el('div', 'kb-col-cards');

      mems.forEach(function(mem) {
        var card = buildCard(mem, sc);
        cards.appendChild(card);
      });

      if (mems.length === 0) {
        var empty = el('div', 'kb-empty');
        empty.textContent = 'No memories';
        cards.appendChild(empty);
      }

      col.appendChild(cards);
      board.appendChild(col);
    });

    container.appendChild(board);
  }

  function buildCard(mem, stageColor) {
    var card = el('div', 'kb-card');
    card.dataset.memId = mem.id;

    var heat = Math.max(0, Math.min(1, mem.heat || 0));
    var stability = mem.stability;
    var interference = mem.interferenceScore || 0;
    var plasticity = Math.max(0, Math.min(1, mem.plasticity || 0));
    var replayCount = mem.accessCount || 0;

    // Heat tint via CSS custom property (used by ::before pseudo-element)
    card.style.setProperty('--card-heat', heat);
    card.style.setProperty('--card-stage-color', stageColor);

    // Card opacity — floor at 0.55
    card.style.opacity = Math.max(0.55, 0.4 + heat * 0.5);

    // Integrity border class (null-safe stability check)
    var borderClass;
    if (stability == null || stability === undefined) {
      borderClass = 'kb-card--neutral';
    } else if (stability > 0.7 && interference < 0.3) {
      borderClass = 'kb-card--healthy';
    } else if (stability > 0.3) {
      borderClass = 'kb-card--consolidating';
    } else if (interference > 0.5) {
      borderClass = 'kb-card--at-risk';
    } else {
      borderClass = 'kb-card--fading';
    }
    card.classList.add(borderClass);

    // Fading indicator for very low heat
    if (heat < 0.1) {
      card.classList.add('kb-card-fading');
    }

    var body = el('div', 'kb-card-body');

    // Content — 2 lines max, 100 chars
    var label = el('div', 'kb-card-label');
    label.textContent = (mem.label || mem.content || '').slice(0, 100);
    body.appendChild(label);

    // Emotion chip — high-signal affective indicator under the label.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildEmotionChip === 'function') {
      var emoChip = JUG._memSci.buildEmotionChip(mem);
      if (emoChip) {
        emoChip.classList.add('ms-emotion--compact');
        body.appendChild(emoChip);
      }
    }

    // Meta row: domain pill + store type badge + relative age
    var meta = el('div', 'kb-card-meta');

    var domain = el('span', 'kb-card-domain');
    domain.textContent = (mem.domain || '').slice(0, 18);
    meta.appendChild(domain);

    var storeType = mem.storeType || (mem.consolidationStage === 'consolidated' ? 'semantic' : 'episodic');
    var storeBadge = el('span', 'kb-card__store-badge');
    if (storeType === 'semantic') {
      storeBadge.classList.add('kb-card__store-badge--semantic');
      storeBadge.textContent = 'SEM';
    } else {
      storeBadge.classList.add('kb-card__store-badge--episodic');
      storeBadge.textContent = 'EP';
    }
    meta.appendChild(storeBadge);

    if (mem._ts) {
      var time = el('span', 'kb-card-time');
      time.textContent = formatTime(mem._ts);
      meta.appendChild(time);
    }
    body.appendChild(meta);

    // Meaning — schema alignment, semantic tags, gist.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildMeaningSection === 'function') {
      var meaning = JUG._memSci.buildMeaningSection(mem);
      if (meaning) {
        meaning.classList.add('ms-meaning--compact');
        body.appendChild(meaning);
      }
    }

    // Scientific measurements — compact variant keeps Kanban column
    // cards dense (6 top rows max; bars + counters only, no text/age).
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildSciencePanel === 'function') {
      var sci = JUG._memSci.buildSciencePanel(mem, 'compact');
      if (sci) body.appendChild(sci);
    }

    // Tags — up to 2
    if (mem.tags && mem.tags.length > 0) {
      var tagsRow = el('div', 'kb-card-tags');
      mem.tags.slice(0, 2).forEach(function(t) {
        var tag = el('span', 'kb-card-tag');
        tag.textContent = t;
        tagsRow.appendChild(tag);
      });
      body.appendChild(tagsRow);
    }

    // Protected badge
    if (mem.isProtected) {
      var shield = el('span', 'kb-badge kb-badge-protected');
      shield.textContent = '\u26A1';
      body.appendChild(shield);
    }

    // Hover-expand scan tier (hidden by default, shown on hover via CSS)
    var scan = el('div', 'kb-card__scan');
    var safeStability = (stability != null) ? Math.max(0, Math.min(1, stability)) : 0;

    // Plasticity bar
    scan.innerHTML =
      '<div class="kb-card__bar">' +
        '<span class="kb-card__bar-label">Plasticity</span>' +
        '<div class="kb-card__bar-track"><div class="kb-card__bar-fill" style="width:' + (plasticity * 100) + '%"></div></div>' +
      '</div>' +
      '<div class="kb-card__bar">' +
        '<span class="kb-card__bar-label">Stability</span>' +
        '<div class="kb-card__bar-track"><div class="kb-card__bar-fill" style="width:' + (safeStability * 100) + '%"></div></div>' +
      '</div>' +
      (interference > 0.3 ? '<span class="kb-card__risk-badge">\u26A0 Interference</span>' : '') +
      (replayCount > 0 ? '<span class="kb-card__meta-badge">\u21BB ' + replayCount + '</span>' : '');

    body.appendChild(scan);
    card.appendChild(body);

    // Tooltip on hover
    card.addEventListener('mouseenter', function() { JUG._tooltip.show(mem); });
    card.addEventListener('mouseleave', function() { JUG._tooltip.hide(); });

    // Click to select/deselect
    card.addEventListener('click', function(e) {
      e.stopPropagation();
      _emitting = true;
      if (selectedId === mem.id) {
        clearHighlight();
        JUG.emit('graph:deselectNode');
      } else {
        highlightMemory(mem.id);
        JUG.emit('graph:selectNode', mem);
      }
      _emitting = false;
    });

    return card;
  }

  function highlightMemory(id) {
    selectedId = id;
    if (!container) return;
    var cards = container.querySelectorAll('.kb-card');
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].dataset.memId === id) {
        cards[i].classList.add('kb-card-selected');
        cards[i].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        cards[i].classList.add('kb-card-dimmed');
      }
    }
  }

  function clearHighlight() {
    selectedId = null;
    if (!container) return;
    var cards = container.querySelectorAll('.kb-card');
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.remove('kb-card-selected', 'kb-card-dimmed');
    }
  }

  function formatTime(ts) {
    var d = new Date(ts);
    var now = new Date();
    var diff = now - d;
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    if (diff < 604800000) return Math.floor(diff / 86400000) + 'd ago';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function miniBar(label, value, color) {
    var pct = Math.max(0, Math.min(100, (value || 0) * 100));
    return '<div class="kb-flow-metric">' +
      '<span class="kb-flow-metric-label">' + label + '</span>' +
      '<div class="kb-flow-metric-bar"><div class="kb-flow-metric-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
      '<span class="kb-flow-metric-val">' + pct.toFixed(0) + '%</span></div>';
  }

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    requestAnimationFrame(init);
  }

  JUG.timelineView = { show: show, hide: hide };
})();
