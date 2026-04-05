// Cortex Pipeline Tree — Horizontal flow, vertical columns per stage
// Each memory flows left → right through pipeline stages
// Lines connect the SAME memory between adjacent columns
(function() {
  var container = null;
  var visible = false;
  var selectedId = null;
  var _emitting = false;

  var STAGE_COLORS = JUG.CONSOLIDATION_COLORS;
  var STAGE_LABELS = JUG.CONSOLIDATION_LABELS || {};
  var DOMAIN_PALETTE = [
    '#E8B840', '#60A0E0', '#40D870', '#C070D0', '#ff3366',
    '#50D0E8', '#E07070', '#8B5CF6', '#F59E0B', '#2DD4BF',
    '#F43F5E', '#6366F1', '#84CC16', '#EC4899', '#14B8A6',
  ];
  var _domColors = {};
  var _domIdx = 0;
  function dc(d) {
    if (!d) return '#50D0E8';
    if (!_domColors[d]) { _domColors[d] = DOMAIN_PALETTE[_domIdx++ % DOMAIN_PALETTE.length]; }
    return _domColors[d];
  }

  var BLOCK = 12;
  var GAP = 3;
  var CELL = BLOCK + GAP;

  function init() {
    container = document.getElementById('sankey-container');
    if (!container) return;
    JUG.on('state:activeView', function(ev) {
      if (ev.value === 'sankey') show(); else hide();
    });
    JUG.on('graph:selectNode', function(n) {
      if (_emitting || !visible || !n) return; highlight(n.id);
    });
    JUG.on('graph:deselectNode', function() {
      if (_emitting || !visible) return; clearHL();
    });
  }

  function show() {
    if (!container) return;
    container.style.display = 'flex';
    visible = true;
    render();
  }
  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
  }

  function render() {
    container.innerHTML = '';
    _domColors = {}; _domIdx = 0;

    var data = JUG.state.lastData || { nodes: [] };
    var mems = (data.nodes || []).filter(function(n) { return n.type === 'memory'; });
    if (JUG._applyExtraFilters) mems = JUG._applyExtraFilters(mems);
    if (!mems.length) {
      container.innerHTML = '<div class="hf-empty">No memories</div>';
      return;
    }

    // Sort by domain then importance
    mems.sort(function(a, b) {
      if (a.domain !== b.domain) return (a.domain || '').localeCompare(b.domain || '');
      return (b.importance || 0) - (a.importance || 0);
    });

    // Compute per-memory flags
    mems.forEach(function(m, i) {
      m._row = i;
      m._dc = dc(m.domain || 'unknown');
      m._novelty = (m.surpriseScore || 0) > 0;
      m._emotional = m.emotion && m.emotion !== 'neutral';
      m._strongEnc = (m.encodingStrength || 0) > 0.5;
      m._active = (m.heat || 0) > 0.1;
      m._stage = m.consolidationStage || 'labile';
    });

    // Count domains
    var domainSet = {};
    mems.forEach(function(m) { domainSet[m.domain || 'unknown'] = true; });
    var domainCount = Object.keys(domainSet).length;

    // Count per stage
    var stageCounts = {};
    mems.forEach(function(m) { stageCounts[m._stage] = (stageCounts[m._stage] || 0) + 1; });

    // Pipeline stages
    var stages = [
      {
        id: 'input', label: 'DOMAINS',
        sub: domainCount + ' domains',
        count: mems.length
      },
      {
        id: 'gate', label: 'WRITE GATE',
        sub: 'Predictive coding',
        ref: 'Friston 2005',
        test: function(m) { return m._novelty; }
      },
      {
        id: 'emotion', label: 'EMOTIONAL TAG',
        sub: 'Priority encoding',
        ref: 'Wang & Bhatt 2024',
        test: function(m) { return m._emotional; }
      },
      {
        id: 'encoding', label: 'ENCODING',
        sub: '\u03B8 phase gating',
        ref: 'Hasselmo 2005',
        test: function(m) { return m._strongEnc; }
      },
      {
        id: 'consol', label: 'CONSOLIDATION',
        sub: 'Stage cascade',
        ref: 'Kandel 2001',
        isConsol: true
      },
      {
        id: 'retention', label: 'RETENTION',
        sub: 'heat > 0.1',
        test: function(m) { return m._active; }
      },
    ];

    var flow = el('div', 'hf-flow');

    stages.forEach(function(stage, si) {
      // Placeholder for connection lines (filled after DOM render)
      if (si > 0) {
        var lineCol = el('div', 'hf-lines');
        lineCol.dataset.stageIdx = si;
        flow.appendChild(lineCol);
      }

      // Column
      var col = el('div', 'hf-col');

      // Rich header
      var header = el('div', 'hf-col-header');
      var titleEl = el('div', 'hf-col-title');
      titleEl.textContent = stage.label;
      header.appendChild(titleEl);

      if (stage.ref) {
        var refEl = el('div', 'hf-col-ref');
        refEl.textContent = stage.ref;
        header.appendChild(refEl);
      }

      var subEl = el('div', 'hf-col-sub');
      subEl.textContent = stage.sub;
      header.appendChild(subEl);

      // Counts in header
      if (stage.test) {
        var passed = mems.filter(function(m) { return stage.test(m); });
        var failed = mems.filter(function(m) { return !stage.test(m); });
        var countsEl = el('div', 'hf-col-counts');
        countsEl.innerHTML =
          '<span class="hf-count-pass">' + passed.length + ' pass</span>' +
          '<span class="hf-count-sep">/</span>' +
          '<span class="hf-count-fail">' + failed.length + ' fail</span>';
        header.appendChild(countsEl);
      } else if (stage.count !== undefined) {
        var countEl = el('div', 'hf-col-total');
        countEl.textContent = stage.count;
        header.appendChild(countEl);
      } else if (stage.isConsol) {
        var consolCounts = el('div', 'hf-col-consol-counts');
        ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'].forEach(function(cs) {
          var c = stageCounts[cs] || 0;
          if (c === 0) return;
          var span = el('span', 'hf-consol-count');
          span.style.color = STAGE_COLORS[cs] || '#50C8E0';
          span.textContent = (STAGE_LABELS[cs] || cs).charAt(0).toUpperCase() + ':' + c;
          consolCounts.appendChild(span);
        });
        header.appendChild(consolCounts);
      }

      col.appendChild(header);

      // Blocks
      var blocksWrap = el('div', 'hf-blocks');
      var positions = {};

      if (stage.isConsol) {
        var consolStages = ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'];
        var rowIdx = 0;
        consolStages.forEach(function(cs) {
          var stageMems = mems.filter(function(m) { return m._stage === cs; });
          if (stageMems.length === 0) return;
          var section = el('div', 'hf-consol-section');
          section.style.borderColor = STAGE_COLORS[cs] || '#50C8E0';
          var sLabel = el('div', 'hf-consol-label');
          sLabel.style.color = STAGE_COLORS[cs] || '#50C8E0';
          sLabel.textContent = (STAGE_LABELS[cs] || cs).toUpperCase() + ' (' + stageMems.length + ')';
          section.appendChild(sLabel);
          stageMems.forEach(function(m) {
            section.appendChild(makeBlock(m));
            positions[m.id] = rowIdx++;
          });
          blocksWrap.appendChild(section);
          rowIdx++; // gap between sections
        });

      } else if (stage.test) {
        var passed = mems.filter(function(m) { return stage.test(m); });
        var failed = mems.filter(function(m) { return !stage.test(m); });
        var rowIdx = 0;

        // Pass group
        if (passed.length > 0) {
          var passSection = el('div', 'hf-gate-section hf-gate-pass');
          passed.forEach(function(m) {
            passSection.appendChild(makeBlock(m));
            positions[m.id] = rowIdx++;
          });
          blocksWrap.appendChild(passSection);
        }

        // Divider
        if (passed.length > 0 && failed.length > 0) {
          blocksWrap.appendChild(el('div', 'hf-gate-divider'));
          rowIdx += 2;
        }

        // Fail group
        if (failed.length > 0) {
          var failSection = el('div', 'hf-gate-section hf-gate-fail');
          failed.forEach(function(m) {
            var b = makeBlock(m);
            b.classList.add('hf-block-fail');
            failSection.appendChild(b);
            positions[m.id] = rowIdx++;
          });
          blocksWrap.appendChild(failSection);
        }

      } else {
        // Domain column: group by domain with colored borders
        var domains = {};
        mems.forEach(function(m) {
          var d = m.domain || 'unknown';
          if (!domains[d]) domains[d] = [];
          domains[d].push(m);
        });
        var rowIdx = 0;
        Object.keys(domains).forEach(function(d) {
          var section = el('div', 'hf-domain-section');
          section.style.borderColor = dc(d);
          var dLabel = el('div', 'hf-domain-label');
          dLabel.style.color = dc(d);
          dLabel.textContent = d + ' (' + domains[d].length + ')';
          section.appendChild(dLabel);
          domains[d].forEach(function(m) {
            section.appendChild(makeBlock(m));
            positions[m.id] = rowIdx++;
          });
          blocksWrap.appendChild(section);
          rowIdx++; // gap between domains
        });
      }

      col.appendChild(blocksWrap);
      flow.appendChild(col);
    });

    container.appendChild(flow);

    // Sync scroll: when any column scrolls, all others follow + redraw lines
    var allScrollable = flow.querySelectorAll('.hf-blocks');
    var syncing = false;
    allScrollable.forEach(function(scrollEl) {
      scrollEl.addEventListener('scroll', function() {
        if (syncing) return;
        syncing = true;
        var top = scrollEl.scrollTop;
        allScrollable.forEach(function(other) {
          if (other !== scrollEl) other.scrollTop = top;
        });
        syncing = false;
        // Redraw lines at new positions
        drawLinesPostRender();
      });
    });

    // Draw connection lines after DOM layout is complete
    requestAnimationFrame(function() {
      requestAnimationFrame(drawLinesPostRender);
    });
  }

  // ── Canvas connection lines — drawn after DOM render ──
  function drawLinesPostRender() {
    if (!container) return;
    var flow = container.querySelector('.hf-flow');
    if (!flow) return;

    var cols = flow.querySelectorAll('.hf-col');
    var lineCols = flow.querySelectorAll('.hf-lines');

    lineCols.forEach(function(lineCol) {
      var si = parseInt(lineCol.dataset.stageIdx);
      if (isNaN(si) || si < 1) return;

      var prevCol = cols[si - 1];
      var nextCol = cols[si];
      if (!prevCol || !nextCol) return;

      // Create canvas filling the line column
      var rect = lineCol.getBoundingClientRect();
      var canvas = document.createElement('canvas');
      var dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.className = 'hf-canvas';
      var ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);

      // Map blocks by memId
      var prevBlocks = {};
      prevCol.querySelectorAll('.hf-block').forEach(function(b) {
        prevBlocks[b.dataset.memId] = b;
      });
      var nextBlocks = {};
      nextCol.querySelectorAll('.hf-block').forEach(function(b) {
        nextBlocks[b.dataset.memId] = b;
      });

      var w = rect.width;
      var memIds = Object.keys(prevBlocks);

      // Store line data for highlight
      lineCol._lineData = [];

      // Draw fail lines first (behind)
      [true, false].forEach(function(drawFail) {
        memIds.forEach(function(memId) {
          var prevB = prevBlocks[memId];
          var nextB = nextBlocks[memId];
          if (!prevB || !nextB) return;

          var isFail = nextB.classList.contains('hf-block-fail');
          if (drawFail !== isFail) return;

          var prevRect = prevB.getBoundingClientRect();
          var nextRect = nextB.getBoundingClientRect();
          var y1 = prevRect.top + prevRect.height / 2 - rect.top;
          var y2 = nextRect.top + nextRect.height / 2 - rect.top;
          var color = prevB.style.background || '#50C8E0';

          lineCol._lineData.push({ memId: memId, y1: y1, y2: y2, color: color, fail: isFail });

          ctx.beginPath();
          ctx.moveTo(0, y1);
          ctx.bezierCurveTo(w * 0.4, y1, w * 0.6, y2, w, y2);
          ctx.strokeStyle = color;
          ctx.lineWidth = isFail ? 0.5 : 1;
          ctx.globalAlpha = isFail ? 0.06 : 0.3;
          if (isFail) {
            ctx.setLineDash([2, 4]);
          } else {
            ctx.setLineDash([]);
          }
          ctx.stroke();
        });
      });

      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      lineCol.innerHTML = '';
      lineCol.appendChild(canvas);
    });
  }

  // ── Redraw lines with highlight ──
  function redrawLinesHighlight(highlightId) {
    if (!container) return;
    var lineCols = container.querySelectorAll('.hf-lines');
    lineCols.forEach(function(lineCol) {
      var canvas = lineCol.querySelector('canvas');
      if (!canvas || !lineCol._lineData) return;

      var dpr = window.devicePixelRatio || 1;
      var ctx = canvas.getContext('2d');
      var w = canvas.width / dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, canvas.height / dpr);

      lineCol._lineData.forEach(function(d) {
        var isHL = d.memId === highlightId;
        ctx.beginPath();
        ctx.moveTo(0, d.y1);
        ctx.bezierCurveTo(w * 0.4, d.y1, w * 0.6, d.y2, w, d.y2);
        ctx.strokeStyle = d.color;

        if (highlightId) {
          if (isHL) {
            ctx.lineWidth = 2.5;
            ctx.globalAlpha = 1;
            ctx.shadowColor = d.color;
            ctx.shadowBlur = 4;
          } else {
            ctx.lineWidth = 0.5;
            ctx.globalAlpha = 0.03;
            ctx.shadowBlur = 0;
          }
        } else {
          ctx.lineWidth = d.fail ? 0.5 : 1;
          ctx.globalAlpha = d.fail ? 0.06 : 0.3;
          ctx.shadowBlur = 0;
        }

        if (d.fail && !isHL) {
          ctx.setLineDash([2, 4]);
        } else {
          ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
      });

      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    });
  }

  function makeBlock(mem) {
    var b = el('div', 'hf-block');
    b.style.background = mem._dc;
    b.dataset.memId = mem.id;
    b.addEventListener('mouseenter', function() { JUG._tooltip.show(mem); });
    b.addEventListener('mouseleave', function() { JUG._tooltip.hide(); });
    b.addEventListener('click', function(e) {
      e.stopPropagation();
      _emitting = true;
      if (selectedId === mem.id) { clearHL(); JUG.emit('graph:deselectNode'); }
      else { highlight(mem.id); JUG.emit('graph:selectNode', mem); }
      _emitting = false;
    });
    return b;
  }

  function highlight(id) {
    selectedId = id;
    if (!container) return;
    container.querySelectorAll('.hf-block').forEach(function(b) {
      b.classList.toggle('hf-block-selected', b.dataset.memId === id);
      b.classList.toggle('hf-block-dimmed', b.dataset.memId !== id);
    });
    redrawLinesHighlight(id);
  }

  function clearHL() {
    selectedId = null;
    if (!container) return;
    container.querySelectorAll('.hf-block').forEach(function(b) {
      b.classList.remove('hf-block-selected', 'hf-block-dimmed');
    });
    redrawLinesHighlight(null);
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
  JUG.sankeyView = { show: show, hide: hide };
})();
