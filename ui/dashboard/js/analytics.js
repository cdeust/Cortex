// Cortex Memory Dashboard — Analytics Panel
// KPI strip + bar charts for types, heat, domains, tags.
// Clickable bars filter the graph view.

(function() {

  function updateAnalytics(data) {
    updateKPIs(data.stats);
    drawTypeChart(data.stats);
    drawHeatChart(data.hot_memories || []);
    drawDomainChart(data.domain_counts || {});
    drawTagChart(data.recent_memories || []);
    drawConsolidationChart(data.stats);
    drawStoreChart(data.hot_memories || []);
  }

  function updateKPIs(s) {
    setText('kpi-total', s.total);
    setText('kpi-active', s.active);
    setText('kpi-entities', s.entities);
    setText('kpi-rels', s.relationships);
    setText('kpi-slots', s.engram_total_slots || 0);
    setText('kpi-occupied', s.engram_occupied_slots || 0);
    setText('kpi-triggers', s.triggers || 0);
    setText('kpi-protected', s.protected || 0);
    // Neuroscience evolution KPIs
    setText('kpi-schemas', s.schema_count || 0);
    setText('kpi-consolidated', s.consolidated || 0);
  }

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function drawTypeChart(s) {
    drawBarChart('chart-types', [
      { label: 'Episodic', value: s.episodic, color: '#26de81', filter: { key: 'activeFilter', value: 'episodic' } },
      { label: 'Semantic', value: s.semantic, color: '#d946ef', filter: { key: 'activeFilter', value: 'semantic' } },
    ]);
  }

  function drawHeatChart(mems) {
    drawBarChart('chart-heat', [
      { label: 'Hot', value: mems.filter(function(m) { return m.heat > 0.7; }).length, color: '#ff4444' },
      { label: 'Warm', value: mems.filter(function(m) { return m.heat > 0.3 && m.heat <= 0.7; }).length, color: '#ffaa00' },
      { label: 'Cold', value: mems.filter(function(m) { return m.heat <= 0.3; }).length, color: '#3a6a9a' },
    ]);
  }

  function drawDomainChart(counts) {
    var palette = ['#00d2ff','#26de81','#d946ef','#ffaa00','#ff4444','#a55eea','#1abc9c','#ff6b35'];
    var entries = Object.entries(counts).sort(function(a, b) { return b[1] - a[1]; }).slice(0, 8);
    drawBarChart('chart-domains', entries.map(function(e, i) {
      return { label: e[0].slice(0, 12), value: e[1], color: palette[i % palette.length],
               filter: { key: 'searchQuery', value: e[0] } };
    }));
  }

  function drawTagChart(memories) {
    var palette = ['#00d2ff','#26de81','#d946ef','#ffaa00','#ff4444','#a55eea','#1abc9c','#ff6b35'];
    var counts = {};
    memories.forEach(function(m) {
      (m.tags || []).forEach(function(t) { counts[t] = (counts[t] || 0) + 1; });
    });
    var top = Object.entries(counts).sort(function(a, b) { return b[1] - a[1]; }).slice(0, 8);
    drawBarChart('chart-tags', top.map(function(e, i) {
      return { label: e[0].slice(0, 10), value: e[1], color: palette[i % palette.length],
               filter: { key: 'searchQuery', value: e[0] } };
    }));
  }

  function drawConsolidationChart(s) {
    drawBarChart('chart-consolidation', [
      { label: 'Labile', value: s.labile || 0, color: '#ff4444' },
      { label: 'Early LTP', value: s.early_ltp || 0, color: '#ffaa00' },
      { label: 'Late LTP', value: s.late_ltp || 0, color: '#26de81' },
      { label: 'Consolidated', value: s.consolidated || 0, color: '#00d2ff' },
      { label: 'Reconsol.', value: s.reconsolidating || 0, color: '#d946ef' },
    ]);
  }

  function drawStoreChart(mems) {
    var hippo = 0, trans = 0, cortical = 0;
    mems.forEach(function(m) {
      var dep = m.hippocampal_dependency || 1.0;
      if (dep > 0.7) hippo++;
      else if (dep > 0.15) trans++;
      else cortical++;
    });
    drawBarChart('chart-stores', [
      { label: 'Hippocampal', value: hippo, color: '#ff6b35' },
      { label: 'Transfer', value: trans, color: '#ffaa00' },
      { label: 'Cortical', value: cortical, color: '#00d2ff' },
    ]);
  }

  // Store click regions for each canvas
  var clickRegions = {};

  function drawBarChart(canvasId, items) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var rect = canvas.parentElement.getBoundingClientRect();
    var dpr = devicePixelRatio;
    canvas.width = rect.width * dpr;
    canvas.style.width = rect.width + 'px';
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height * dpr);

    if (!items.length) return;
    var maxVal = Math.max(1, Math.max.apply(null, items.map(function(d) { return d.value; })));
    var barH = 14 * dpr, gap = 6 * dpr, labelW = 70 * dpr;
    var chartW = canvas.width - labelW - 40 * dpr;

    // Store click regions for this canvas
    var regions = [];

    items.forEach(function(d, i) {
      var y = i * (barH + gap) + 4 * dpr;

      // Store the click region
      regions.push({
        y: y / dpr,
        h: barH / dpr,
        filter: d.filter || null,
        label: d.label,
      });

      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = (9 * dpr) + 'px JetBrains Mono';
      ctx.textAlign = 'right';
      ctx.fillText(d.label, labelW - 6 * dpr, y + barH * 0.75);

      var w = (d.value / maxVal) * chartW;
      ctx.fillStyle = d.color;
      ctx.globalAlpha = 0.25;
      ctx.fillRect(labelW, y, w, barH);
      ctx.globalAlpha = 0.8;
      ctx.fillRect(labelW, y, w, 2 * dpr);
      ctx.globalAlpha = 1;

      ctx.fillStyle = 'rgba(255,255,255,0.6)';
      ctx.textAlign = 'left';
      ctx.fillText(d.value, labelW + w + 6 * dpr, y + barH * 0.75);
    });

    clickRegions[canvasId] = regions;

    // Attach click handler once
    if (!canvas._hasClickHandler) {
      canvas._hasClickHandler = true;
      canvas.style.cursor = 'pointer';
      canvas.addEventListener('click', function(e) {
        var canvasRect = canvas.getBoundingClientRect();
        var clickY = e.clientY - canvasRect.top;
        var regions = clickRegions[canvasId] || [];
        for (var r = 0; r < regions.length; r++) {
          if (clickY >= regions[r].y && clickY <= regions[r].y + regions[r].h && regions[r].filter) {
            // Apply the filter
            JMD.setState(regions[r].filter.key, regions[r].filter.value);

            // Also update the filter buttons if changing activeFilter
            if (regions[r].filter.key === 'activeFilter') {
              document.querySelectorAll('#type-filter-bar .filter-btn').forEach(function(b) {
                b.classList.toggle('active', b.dataset.type === regions[r].filter.value);
              });
            }
            // If setting search query, update the search box
            if (regions[r].filter.key === 'searchQuery') {
              document.getElementById('search-box').value = regions[r].filter.value;
            }
            // Switch to graph view
            if (JMD.state.activeView !== 'graph') {
              JMD.setState('activeView', 'graph');
              document.querySelectorAll('#sidebar .nav-item').forEach(function(b) {
                b.classList.toggle('active', b.dataset.view === 'graph');
              });
            }
            break;
          }
        }
      });
    }
  }

  // Toggle analytics panel
  JMD.on('state:analyticsOpen', function(e) {
    document.getElementById('analytics-panel').classList.toggle('open', e.value);
    var btn = document.getElementById('analytics-toggle');
    if (btn) btn.classList.toggle('active', e.value);
  });

  JMD.on('data:refresh', updateAnalytics);
})();
