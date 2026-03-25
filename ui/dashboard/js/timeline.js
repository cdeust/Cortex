// Cortex Memory Dashboard — Timeline View
// Chronological memory display grouped by time windows.

(function() {

  var TIME_GROUPS = ['Last Hour', 'Today', 'Yesterday', 'This Week', 'Older'];

  function groupByTime(memories) {
    var groups = {};
    var now = Date.now();
    memories.forEach(function(m) {
      var diff = (now - new Date(m.created_at).getTime()) / 3600000;
      var label;
      if (diff < 1) label = 'Last Hour';
      else if (diff < 24) label = 'Today';
      else if (diff < 48) label = 'Yesterday';
      else if (diff < 168) label = 'This Week';
      else label = 'Older';
      if (!groups[label]) groups[label] = [];
      groups[label].push(m);
    });
    return groups;
  }

  function renderTimeline(data) {
    var el = document.getElementById('timeline-container');
    var memories = data.recent_memories || [];
    if (!memories.length) {
      el.innerHTML = '<div style="padding:40px;color:#3a4a5a;text-align:center">No memories stored yet</div>';
      return;
    }

    var groups = groupByTime(memories);
    el.innerHTML = TIME_GROUPS.filter(function(l) { return groups[l]; }).map(function(label) {
      return renderGroup(label, groups[label]);
    }).join('');
  }

  function renderGroup(label, items) {
    return '<div class="tl-group">' +
      '<div class="tl-group-header" onclick="JMD.toggleTlGroup(this)">' +
        '<span class="count-badge">' + items.length + '</span> ' + label +
      '</div>' +
      '<div class="tl-items">' + items.map(renderItem).join('') + '</div>' +
    '</div>';
  }

  function renderItem(m) {
    var hc = JMD.heatColorCSS(m.heat);
    var tags = (m.tags || []).map(function(t) {
      return '<span class="tl-tag">' + JMD.escHtml(t) + '</span>';
    }).join('');

    return '<div class="tl-item" onclick="JMD.toggleTlItem(this)">' +
      '<div class="tl-row">' +
        '<span class="tl-type ' + (m.store_type || 'episodic') + '">' + (m.store_type || 'episodic').slice(0,4) + '</span>' +
        '<span class="tl-heat" style="color:' + hc + '">' + m.heat.toFixed(2) + '</span>' +
        '<span class="tl-content">' + JMD.escHtml(m.content) + '</span>' +
        '<span class="tl-time">' + JMD.timeAgo(m.created_at) + '</span>' +
      '</div>' +
      '<div class="tl-detail">' +
        '<div style="line-height:1.7">' + JMD.escHtml(m.content) + '</div>' +
        '<div class="tl-meta-grid">' +
          '<div class="tl-ml">Heat</div><div class="tl-mv" style="color:' + hc + '">' + m.heat.toFixed(4) + '</div>' +
          '<div class="tl-ml">Importance</div><div class="tl-mv">' + (m.importance || 0).toFixed(3) + '</div>' +
          '<div class="tl-ml">Domain</div><div class="tl-mv">' + (m.domain || '\u2014') + '</div>' +
          '<div class="tl-ml">Created</div><div class="tl-mv">' + JMD.timeAgo(m.created_at) + '</div>' +
        '</div>' +
        '<div class="tl-tags">' + tags + '</div>' +
      '</div>' +
    '</div>';
  }

  JMD.toggleTlGroup = function(header) {
    header.nextElementSibling.classList.toggle('collapsed');
  };

  JMD.toggleTlItem = function(item) {
    item.querySelector('.tl-detail').classList.toggle('open');
    var c = item.querySelector('.tl-content');
    c.style.whiteSpace = c.style.whiteSpace === 'normal' ? 'nowrap' : 'normal';
    c.style.overflow = c.style.whiteSpace === 'normal' ? 'visible' : 'hidden';
  };

  JMD.on('data:refresh', function(data) {
    if (JMD.state.activeView === 'timeline') renderTimeline(data);
  });
  JMD.on('state:activeView', function(e) {
    if (e.value === 'timeline' && JMD.state.lastData) renderTimeline(JMD.state.lastData);
  });
})();
