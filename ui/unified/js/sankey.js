// Cortex Pipeline Tree — Horizontal flow, vertical columns per stage
// Each pipeline stage is a column, memories flow left → right
// SVG Bezier lines use full screen width for visibility
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

    mems.sort(function(a, b) {
      if (a.domain !== b.domain) return (a.domain || '').localeCompare(b.domain || '');
      return (b.importance || 0) - (a.importance || 0);
    });

    mems.forEach(function(m, i) {
      m._row = i;
      m._dc = dc(m.domain || 'unknown');
      m._novelty = (m.surpriseScore || 0) > 0.05;
      m._emotional = m.emotion && m.emotion !== 'neutral';
      m._strongEnc = (m.encodingStrength || 0) > 0.5;
      m._active = (m.heat || 0) > 0.1;
      m._stage = m.consolidationStage || 'labile';
    });

    var stages = [
      { id: 'input', label: 'DOMAINS', sub: mems.length + ' mem' },
      { id: 'gate', label: 'WRITE GATE', sub: 'Friston 2005', test: function(m) { return m._novelty; } },
      { id: 'emotion', label: 'EMOTIONAL', sub: 'Wang & Bhatt 2024', test: function(m) { return m._emotional; } },
      { id: 'encoding', label: 'ENCODING', sub: 'Hasselmo 2005', test: function(m) { return m._strongEnc; } },
      { id: 'consol', label: 'CONSOLIDATION', sub: 'Kandel 2001', isConsol: true },
      { id: 'retention', label: 'RETENTION', sub: 'heat > 0.1', test: function(m) { return m._active; } },
    ];

    var flow = el('div', 'hf-flow');
    var prevPositions = null;

    stages.forEach(function(stage, si) {
      // SVG lines between columns
      if (prevPositions && si > 0) {
        flow.appendChild(buildLines(mems, prevPositions, stage));
      }

      // Column
      var col = el('div', 'hf-col');
      var header = el('div', 'hf-col-header');
      header.innerHTML =
        '<div class="hf-col-title">' + stage.label + '</div>' +
        '<div class="hf-col-sub">' + stage.sub + '</div>';
      col.appendChild(header);

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
          sLabel.textContent = (STAGE_LABELS[cs] || cs).toUpperCase() + ' ' + stageMems.length;
          section.appendChild(sLabel);
          stageMems.forEach(function(m) {
            section.appendChild(makeBlock(m));
            positions[m.id] = rowIdx++;
          });
          blocksWrap.appendChild(section);
          rowIdx++;
        });
      } else if (stage.test) {
        var passed = mems.filter(function(m) { return stage.test(m); });
        var failed = mems.filter(function(m) { return !stage.test(m); });
        var rowIdx = 0;
        var pl = el('div', 'hf-gate-label hf-pass-label');
        pl.textContent = '\u2713 ' + passed.length;
        blocksWrap.appendChild(pl);
        passed.forEach(function(m) {
          var b = makeBlock(m); b.classList.add('hf-block-pass');
          blocksWrap.appendChild(b);
          positions[m.id] = rowIdx++;
        });
        blocksWrap.appendChild(el('div', 'hf-gate-divider'));
        rowIdx += 2;
        var fl = el('div', 'hf-gate-label hf-fail-label');
        fl.textContent = '\u2717 ' + failed.length;
        blocksWrap.appendChild(fl);
        failed.forEach(function(m) {
          var b = makeBlock(m); b.classList.add('hf-block-fail');
          blocksWrap.appendChild(b);
          positions[m.id] = rowIdx++;
        });
      } else {
        mems.forEach(function(m, i) {
          blocksWrap.appendChild(makeBlock(m));
          positions[m.id] = i;
        });
      }

      col.appendChild(blocksWrap);
      flow.appendChild(col);
      prevPositions = positions;
    });

    container.appendChild(flow);

    // Legend
    var legend = el('div', 'hf-legend');
    var seen = {};
    mems.forEach(function(m) {
      var d = m.domain || 'unknown';
      if (seen[d]) return; seen[d] = true;
      var item = el('span', 'hf-legend-item');
      item.innerHTML = '<span class="hf-legend-dot" style="background:' + m._dc + '"></span>' + d;
      legend.appendChild(item);
    });
    container.appendChild(legend);
  }

  function buildLines(mems, prevPos, stage) {
    var lineCol = el('div', 'hf-lines');
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'hf-svg');

    var nextPos = {};
    if (stage.isConsol) {
      var idx = 0;
      ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'].forEach(function(cs) {
        var sm = mems.filter(function(m) { return m._stage === cs; });
        sm.forEach(function(m) { nextPos[m.id] = idx++; });
        if (sm.length > 0) idx++;
      });
    } else if (stage.test) {
      var passed = mems.filter(function(m) { return stage.test(m); });
      var failed = mems.filter(function(m) { return !stage.test(m); });
      var idx = 0;
      passed.forEach(function(m) { nextPos[m.id] = idx++; });
      idx += 2;
      failed.forEach(function(m) { nextPos[m.id] = idx++; });
    } else {
      mems.forEach(function(m, i) { nextPos[m.id] = i; });
    }

    var maxRow = 0;
    Object.values(prevPos).concat(Object.values(nextPos)).forEach(function(v) {
      if (v > maxRow) maxRow = v;
    });
    var svgH = (maxRow + 1) * CELL + 60;
    svg.setAttribute('viewBox', '0 0 100 ' + svgH);
    svg.setAttribute('preserveAspectRatio', 'none');

    var headerOff = 52;

    // Render fail lines first (behind)
    mems.forEach(function(m) {
      var fromY = prevPos[m.id];
      var toY = nextPos[m.id];
      if (fromY === undefined || toY === undefined) return;
      var isFail = stage.test && !stage.test(m);
      if (!isFail) return;
      svg.appendChild(makePath(fromY, toY, headerOff, m._dc, m.id, true));
    });
    // Then pass lines on top
    mems.forEach(function(m) {
      var fromY = prevPos[m.id];
      var toY = nextPos[m.id];
      if (fromY === undefined || toY === undefined) return;
      var isFail = stage.test && !stage.test(m);
      if (isFail) return;
      svg.appendChild(makePath(fromY, toY, headerOff, m._dc, m.id, false));
    });

    lineCol.appendChild(svg);
    return lineCol;
  }

  function makePath(fromRow, toRow, offset, color, memId, isFail) {
    var y1 = offset + fromRow * CELL + BLOCK / 2;
    var y2 = offset + toRow * CELL + BLOCK / 2;
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    var d = 'M 0,' + y1 + ' C 40,' + y1 + ' 60,' + y2 + ' 100,' + y2;
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', color);
    path.setAttribute('data-mem-id', memId);
    path.setAttribute('class', isFail ? 'hf-line-fail' : 'hf-line-pass');
    return path;
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
    container.querySelectorAll('.hf-svg path').forEach(function(p) {
      if (p.getAttribute('data-mem-id') === id) p.classList.add('hf-line-hl');
      else p.style.opacity = '0.02';
    });
  }

  function clearHL() {
    selectedId = null;
    if (!container) return;
    container.querySelectorAll('.hf-block').forEach(function(b) {
      b.classList.remove('hf-block-selected', 'hf-block-dimmed');
    });
    container.querySelectorAll('.hf-svg path').forEach(function(p) {
      p.classList.remove('hf-line-hl');
      p.style.opacity = '';
    });
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
