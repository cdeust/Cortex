// Cortex Memory Dashboard — Analytics
(function() {
  var CMD = window.CMD;

  CMD.showChartTip = function(e, html) {
    var el = document.getElementById('chart-tooltip-brain'); el.innerHTML = html; el.style.display = 'block';
    el.style.left = Math.min(e.clientX + 12, window.innerWidth - 230) + 'px'; el.style.top = Math.min(e.clientY - 10, window.innerHeight - 60) + 'px';
  };
  CMD.hideChartTip = function() { document.getElementById('chart-tooltip-brain').style.display = 'none'; };

  CMD.setupCanvas = function(id, height) {
    var canvas = document.getElementById(id); if (!canvas) return null;
    var dpr = window.devicePixelRatio || 1, w = CMD.CHART_W;
    canvas.style.width = w + 'px'; canvas.style.height = height + 'px'; canvas.width = w * dpr; canvas.height = height * dpr;
    var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr); return { ctx: ctx, w: w, h: height };
  };

  CMD.computeAnalytics = function() {
    var totalMessages = 0, totalMs = 0, totalBytes = 0, sessionCount = 0;
    var heatmap = Array.from({ length: 7 }, function() { return new Array(24).fill(0); });
    var now = Date.now(), weeklyMap = {}, categories = {}, tools = {};
    var buckets = { '<1m': 0, '1-5m': 0, '5-30m': 0, '30m-2h': 0, '>2h': 0 }, projects = {};
    CMD.nodes.forEach(function(n) {
      if (n.nodeType !== 'conversation') return;
      sessionCount++; totalMessages += n.messageCount || 0; totalBytes += n.fileSize || 0;
      if (n.startedAt && n.endedAt) { var ms = new Date(n.endedAt) - new Date(n.startedAt); totalMs += ms; var mins = ms / 60000; if (mins < 1) buckets['<1m']++; else if (mins < 5) buckets['1-5m']++; else if (mins < 30) buckets['5-30m']++; else if (mins < 120) buckets['30m-2h']++; else buckets['>2h']++; }
      if (n.startedAt) { var d = new Date(n.startedAt); heatmap[d.getDay()][d.getHours()]++; if (now - d.getTime() <= 90 * 86400000) { var ws = new Date(d); ws.setDate(d.getDate() - d.getDay()); weeklyMap[ws.toISOString().slice(0, 10)] = (weeklyMap[ws.toISOString().slice(0, 10)] || 0) + 1; } }
      categories[n.category || 'general'] = (categories[n.category || 'general'] || 0) + 1;
      (n.toolsUsed || []).forEach(function(t) { tools[t] = (tools[t] || 0) + 1; });
      projects[CMD.cleanProject(n.project)] = (projects[CMD.cleanProject(n.project)] || 0) + 1;
    });
    return { sessions: sessionCount, totalMessages: totalMessages, totalHours: totalMs / 3600000, totalMB: totalBytes / 1048576, heatmap: heatmap, weeklyTrend: Object.entries(weeklyMap).sort(function(a, b) { return a[0].localeCompare(b[0]); }), categories: categories, tools: tools, buckets: buckets, topProjects: Object.entries(projects).sort(function(a, b) { return b[1] - a[1]; }).slice(0, 10) };
  };

  CMD.drawHeatmap = function(data) {
    var r = CMD.setupCanvas('a-chart-heatmap', 120); if (!r) return;
    var ctx = r.ctx, w = r.w, h = r.h, days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var labelW = 30, cellW = (w - labelW) / 24, cellH = h / 7, maxVal = 1;
    data.heatmap.forEach(function(row) { row.forEach(function(v) { if (v > maxVal) maxVal = v; }); });
    ctx.font = '8px SF Mono,monospace'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (var d = 0; d < 7; d++) { ctx.fillStyle = 'rgba(255,255,255,0.3)'; ctx.fillText(days[d], labelW - 4, d * cellH + cellH / 2);
      for (var hr = 0; hr < 24; hr++) { var t = data.heatmap[d][hr] / maxVal; ctx.fillStyle = CMD.lerpColor(t); ctx.fillRect(labelW + hr * cellW + 1, d * cellH + 1, cellW - 2, cellH - 2);
        if (data.heatmap[d][hr] > 0) { ctx.fillStyle = t > 0.5 ? '#000' : 'rgba(255,255,255,0.7)'; ctx.textAlign = 'center'; ctx.font = '7px SF Mono,monospace'; ctx.fillText(data.heatmap[d][hr], labelW + hr * cellW + cellW / 2, d * cellH + cellH / 2); ctx.textAlign = 'right'; ctx.font = '8px SF Mono,monospace'; } } }
    ctx.fillStyle = 'rgba(255,255,255,0.2)'; ctx.textAlign = 'center'; ctx.font = '7px SF Mono,monospace';
    for (var hr = 0; hr < 24; hr += 3) ctx.fillText(hr + '', labelW + hr * cellW + cellW / 2, h - 2);
    var canvas = document.getElementById('a-chart-heatmap'); canvas._heatData = data.heatmap;
    if (!CMD._bindState['a-chart-heatmap']) { CMD._bindState['a-chart-heatmap'] = true;
      var dFull = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      function getCell(e) { var rect = canvas.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top; var day = Math.floor(my / (120 / 7)), hr = Math.floor((mx - labelW) / ((rect.width - labelW) / 24)); return (day >= 0 && day < 7 && hr >= 0 && hr < 24 && mx >= labelW) ? { day: day, hr: hr } : null; }
      canvas.addEventListener('mousemove', function(e) { var c = getCell(e); if (c) { var v = (canvas._heatData || [])[c.day] ? (canvas._heatData[c.day][c.hr] || 0) : 0; canvas.style.cursor = v > 0 ? 'pointer' : 'default'; CMD.showChartTip(e, '<strong>' + dFull[c.day] + ' ' + c.hr + ':00</strong><br>' + v + ' sessions'); } else { canvas.style.cursor = 'default'; CMD.hideChartTip(); } });
      canvas.addEventListener('mouseleave', function() { canvas.style.cursor = 'default'; CMD.hideChartTip(); }); }
  };

  CMD.drawTimeline = function(data) {
    var r = CMD.setupCanvas('a-chart-timeline', 100); if (!r) return;
    var ctx = r.ctx, w = r.w, h = r.h;
    if (data.weeklyTrend.length < 2) { ctx.fillStyle = 'rgba(255,255,255,0.2)'; ctx.font = '10px SF Mono,monospace'; ctx.textAlign = 'center'; ctx.fillText('Not enough data', w / 2, h / 2); return; }
    var maxVal = Math.max.apply(null, data.weeklyTrend.map(function(d) { return d[1]; }).concat([1]));
    var pad = { l: 28, r: 8, t: 8, b: 16 }, pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
    ctx.beginPath(); ctx.moveTo(pad.l, pad.t + ph);
    data.weeklyTrend.forEach(function(item, i) { ctx.lineTo(pad.l + (i / (data.weeklyTrend.length - 1)) * pw, pad.t + ph - (item[1] / maxVal) * ph); });
    ctx.lineTo(pad.l + pw, pad.t + ph); ctx.closePath();
    var grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + ph); grad.addColorStop(0, 'rgba(0,210,255,0.25)'); grad.addColorStop(1, 'rgba(0,210,255,0.02)'); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); data.weeklyTrend.forEach(function(item, i) { var x = pad.l + (i / (data.weeklyTrend.length - 1)) * pw, y = pad.t + ph - (item[1] / maxVal) * ph; if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    ctx.strokeStyle = 'rgba(0,210,255,0.85)'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.25)'; ctx.font = '8px SF Mono,monospace'; ctx.textAlign = 'right'; ctx.fillText(maxVal, pad.l - 4, pad.t + 8); ctx.fillText('0', pad.l - 4, pad.t + ph);
    ctx.textAlign = 'center'; var step = Math.max(1, Math.floor(data.weeklyTrend.length / 4));
    for (var i = 0; i < data.weeklyTrend.length; i += step) ctx.fillText(data.weeklyTrend[i][0].slice(5), pad.l + (i / (data.weeklyTrend.length - 1)) * pw, h - 2);
  };

  CMD.drawHorizontalBars = function(canvasId, entries, height, colorFn, chartType) {
    var r = CMD.setupCanvas(canvasId, height); if (!r || !entries.length) return;
    var ctx = r.ctx, w = r.w; var maxVal = Math.max.apply(null, entries.map(function(e) { return e[1]; }).concat([1]));
    var total = entries.reduce(function(s, e) { return s + e[1]; }, 0);
    var barH = Math.min(16, (height - 4) / entries.length); ctx.font = '9px SF Mono,monospace';
    var labelW = Math.min(ctx.measureText('W'.repeat(14)).width + 8, w * 0.45), barW = w - labelW - 40;
    var canvas = document.getElementById(canvasId), hovIdx = canvas._hoveredIndex !== undefined ? canvas._hoveredIndex : -1;
    entries.forEach(function(pair, i) {
      var y = i * barH + 2, isH = i === hovIdx;
      ctx.fillStyle = isH ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.4)'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'; ctx.fillText(CMD.smartTrunc(pair[0], 18), labelW - 4, y + barH / 2);
      var bw = (pair[1] / maxVal) * barW; ctx.globalAlpha = isH ? 1 : 0.85; ctx.fillStyle = typeof colorFn === 'function' ? colorFn(pair[0]) : (colorFn || 'rgba(255,255,255,0.3)'); ctx.fillRect(labelW, y + 2, bw, barH - 4);
      if (isH) { ctx.fillStyle = 'rgba(255,255,255,0.15)'; ctx.fillRect(labelW, y + 2, bw, barH - 4); }
      ctx.globalAlpha = 1; ctx.fillStyle = isH ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.35)'; ctx.textAlign = 'left'; ctx.fillText(pair[1], labelW + bw + 4, y + barH / 2);
    });
    canvas._hitRegions = entries.map(function(pair, i) { return { y: i * barH + 2, h: barH, label: pair[0], val: pair[1] }; });
    canvas._chartType = chartType; canvas._total = total;
    if (!CMD._bindState[canvasId]) { CMD._bindState[canvasId] = true; canvas._hoveredIndex = -1;
      canvas.addEventListener('click', function(e) { var rect = canvas.getBoundingClientRect(), my = e.clientY - rect.top; var hit = (canvas._hitRegions || []).find(function(r) { return my >= r.y && my < r.y + r.h; }); if (hit && canvas._chartType) { CMD.activeChartFilter = (CMD.activeChartFilter && CMD.activeChartFilter.type === canvas._chartType && CMD.activeChartFilter.label === hit.label) ? null : { type: canvas._chartType, label: hit.label }; CMD.applyFilters(); } });
      canvas.addEventListener('mousemove', function(e) { var rect = canvas.getBoundingClientRect(), my = e.clientY - rect.top; var regions = canvas._hitRegions || []; var idx = regions.findIndex(function(r) { return my >= r.y && my < r.y + r.h; }); canvas.style.cursor = idx >= 0 ? 'pointer' : 'default'; if (idx >= 0) { var hit = regions[idx]; CMD.showChartTip(e, '<strong style="color:#fff">' + hit.label + '</strong>: ' + hit.val + ' (' + ((hit.val / (canvas._total || 1)) * 100).toFixed(1) + '%)'); } else CMD.hideChartTip(); if (idx !== canvas._hoveredIndex) { canvas._hoveredIndex = idx; CMD.renderAnalytics(); } });
      canvas.addEventListener('mouseleave', function() { canvas.style.cursor = 'default'; canvas._hoveredIndex = -1; CMD.hideChartTip(); CMD.renderAnalytics(); }); }
  };

  CMD.drawHistogram = function(data) {
    var r = CMD.setupCanvas('a-chart-quality', 100); if (!r) return;
    var ctx = r.ctx, w = r.w, h = r.h, entries = Object.entries(data.buckets);
    var maxVal = Math.max.apply(null, entries.map(function(e) { return e[1]; }).concat([1]));
    var pad = { l: 8, r: 8, t: 8, b: 20 }, pw = w - 16, ph = h - 28, bw = pw / entries.length;
    var colors = ['#ff4444', '#ff8800', 'rgba(0,210,255,0.8)', '#26de81', '#a55eea'];
    entries.forEach(function(pair, i) { var val = pair[1], bh = (val / maxVal) * ph, x = pad.l + i * bw + 4, y = pad.t + ph - bh;
      ctx.fillStyle = colors[i] || 'rgba(255,255,255,0.4)'; ctx.globalAlpha = 0.65; ctx.fillRect(x, y, bw - 8, bh); ctx.globalAlpha = 1;
      ctx.fillStyle = 'rgba(255,255,255,0.55)'; ctx.font = '9px SF Mono,monospace'; ctx.textAlign = 'center'; if (val > 0) ctx.fillText(val, x + (bw - 8) / 2, y - 4);
      ctx.fillStyle = 'rgba(255,255,255,0.3)'; ctx.font = '8px SF Mono,monospace'; ctx.fillText(pair[0], x + (bw - 8) / 2, h - 4); });
  };

  CMD.renderAnalytics = function() {
    var d = CMD.computeAnalytics();
    document.getElementById('kpi-b-sessions').textContent = d.sessions.toLocaleString();
    document.getElementById('kpi-b-messages').textContent = d.totalMessages > 999 ? (d.totalMessages / 1000).toFixed(1) + 'K' : d.totalMessages;
    document.getElementById('kpi-b-hours').textContent = d.totalHours.toFixed(1);
    document.getElementById('kpi-b-mb').textContent = d.totalMB.toFixed(1);
    CMD.drawHeatmap(d); CMD.drawTimeline(d);
    var catE = Object.entries(d.categories).sort(function(a, b) { return b[1] - a[1]; });
    CMD.drawHorizontalBars('a-chart-categories', catE, Math.max(catE.length, 1) * 16 + 4, function(l) { return (CMD.CATEGORY_COLORS[l] || '#666') + 'aa'; }, 'categories');
    var toolE = Object.entries(d.tools).sort(function(a, b) { return b[1] - a[1]; }).slice(0, 10);
    CMD.drawHorizontalBars('a-chart-tools', toolE, Math.max(toolE.length, 1) * 16 + 4, 'rgba(165,94,234,0.65)', 'tools');
    CMD.drawHistogram(d);
    CMD.drawHorizontalBars('a-chart-projects', d.topProjects, Math.max(d.topProjects.length, 1) * 16 + 4, 'rgba(0,210,255,0.45)', 'projects');
    // Consolidation stages
    var stageData = {}, storeData = { hippocampal: 0, transitional: 0, cortical: 0 };
    CMD.nodes.filter(function(n) { return n.id && n.id.startsWith('m_'); }).forEach(function(n) { var s = n.consolidation_stage || 'labile'; stageData[s] = (stageData[s] || 0) + 1; var dep = n.hippocampal_dependency || 1; if (dep > 0.7) storeData.hippocampal++; else if (dep > 0.15) storeData.transitional++; else storeData.cortical++; });
    var sc = { labile: '#ff4444', early_ltp: '#ffaa00', late_ltp: '#26de81', consolidated: '#00d2ff', reconsolidating: '#d946ef' };
    var stE = Object.entries(stageData).sort(function(a, b) { return b[1] - a[1]; });
    CMD.drawHorizontalBars('a-chart-consolidation', stE, Math.max(stE.length, 1) * 16 + 4, function(l) { return (sc[l] || '#666') + 'cc'; }, 'stages');
    var stC = { hippocampal: '#ff6b35', transitional: '#ffaa00', cortical: '#00d2ff' };
    var storeE = Object.entries(storeData).filter(function(e) { return e[1] > 0; });
    CMD.drawHorizontalBars('a-chart-stores', storeE, Math.max(storeE.length, 1) * 16 + 4, function(l) { return (stC[l] || '#666') + 'cc'; }, 'stores');
    if (CMD.renderBenchmarks) CMD.renderBenchmarks();
  };

  CMD.toggleAnalytics = function() {
    CMD.analyticsOpen = !CMD.analyticsOpen;
    document.getElementById('analytics-brain').classList.toggle('open', CMD.analyticsOpen);
    document.getElementById('analytics-toggle-brain').classList.toggle('active', CMD.analyticsOpen);
    if (CMD.analyticsOpen) setTimeout(CMD.renderAnalytics, 420);
  };

  CMD.closeAnalytics = function() {
    CMD.analyticsOpen = false;
    document.getElementById('analytics-brain').classList.remove('open');
    document.getElementById('analytics-toggle-brain').classList.remove('active');
  };
})();
