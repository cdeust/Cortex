// Cortex Memory Dashboard — Benchmarks
(function() {
  var CMD = window.CMD;

  CMD.BENCHMARKS = {
    longmemeval: { recall_10: 97.0, mrr: 0.855, questions: 500, paper_best: 78.4 },
    locomo: { recall_10: 84.4, mrr: 0.599, questions: 1982 },
    beam: {
      overall_mrr: 0.517, questions: 395, paper_best: 0.329,
      abilities: {
        temporal_reasoning: 0.814,
        contradiction_resolution: 0.846,
        knowledge_update: 0.800,
        multi_session_reasoning: 0.755,
        event_ordering: 0.407
      }
    }
  };

  function pct(val, max) {
    return Math.min(100, (val / max) * 100).toFixed(1);
  }

  function barHtml(label, cortexVal, maxVal, baselineVal, unit) {
    var cortexPct = pct(cortexVal, maxVal);
    var valStr = unit === '%' ? cortexVal.toFixed(1) + '%' : cortexVal.toFixed(3);
    var html = '<div class="bench-row">';
    html += '<div class="bench-label">' + label + '</div>';
    html += '<div class="bench-bar-bg">';
    html += '<div class="bench-bar cortex" style="width:' + cortexPct + '%"></div>';
    if (baselineVal !== undefined) {
      var blPct = pct(baselineVal, maxVal);
      html += '<div class="bench-bar baseline" style="width:' + blPct + '%"></div>';
    }
    html += '</div>';
    html += '<div class="bench-val">' + valStr + '</div>';
    html += '</div>';
    return html;
  }

  CMD.renderBenchmarks = function() {
    var container = document.getElementById('a-benchmarks');
    if (!container) return;

    var B = CMD.BENCHMARKS;
    var html = '';

    // LongMemEval
    html += '<div class="bench-card">';
    html += '<div class="bench-card-title">LongMemEval (ICLR 2025) \u2014 ' + B.longmemeval.questions + ' Qs</div>';
    html += barHtml('R@10', B.longmemeval.recall_10, 100, B.longmemeval.paper_best, '%');
    html += barHtml('MRR', B.longmemeval.mrr, 1.0, undefined, '');
    html += '<div style="font-size:7px;color:rgba(255,255,255,0.2);margin-top:4px">';
    html += '<span style="display:inline-block;width:8px;height:4px;background:rgba(0,210,255,0.7);border-radius:1px;margin-right:3px"></span>Cortex';
    html += '<span style="display:inline-block;width:8px;height:4px;background:rgba(255,68,68,0.4);border-radius:1px;margin:0 3px 0 8px"></span>Paper best (' + B.longmemeval.paper_best + '%)';
    html += '</div>';
    html += '</div>';

    // LoCoMo
    html += '<div class="bench-card">';
    html += '<div class="bench-card-title">LoCoMo (ACL 2024) \u2014 ' + B.locomo.questions + ' Qs</div>';
    html += barHtml('R@10', B.locomo.recall_10, 100, undefined, '%');
    html += barHtml('MRR', B.locomo.mrr, 1.0, undefined, '');
    html += '</div>';

    // BEAM
    html += '<div class="bench-card">';
    html += '<div class="bench-card-title">BEAM (ICLR 2026) \u2014 ' + B.beam.questions + ' Qs</div>';
    html += barHtml('Overall', B.beam.overall_mrr, 1.0, B.beam.paper_best, '');
    var abilities = B.beam.abilities;
    var abilityKeys = Object.keys(abilities);
    abilityKeys.forEach(function(key) {
      var label = key.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
      // Shorten long labels
      if (label.length > 12) label = label.split(' ').map(function(w) { return w.slice(0, 4); }).join(' ');
      html += barHtml(label, abilities[key], 1.0, undefined, '');
    });
    html += '<div style="font-size:7px;color:rgba(255,255,255,0.2);margin-top:4px">';
    html += '<span style="display:inline-block;width:8px;height:4px;background:rgba(0,210,255,0.7);border-radius:1px;margin-right:3px"></span>Cortex';
    html += '<span style="display:inline-block;width:8px;height:4px;background:rgba(255,68,68,0.4);border-radius:1px;margin:0 3px 0 8px"></span>Paper best (' + B.beam.paper_best + ')';
    html += '</div>';
    html += '</div>';

    container.innerHTML = html;
  };
})();
