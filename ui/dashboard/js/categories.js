// Cortex Memory Dashboard — Categories View
// Groups memories by category with expandable cards.

(function() {

  function renderCategories(data) {
    var el = document.getElementById('categories-container');
    var memories = data.recent_memories || [];
    if (!memories.length) {
      el.innerHTML = '<div style="padding:40px;color:#3a4a5a;text-align:center;grid-column:1/-1">No memories stored yet</div>';
      return;
    }

    var groups = groupByCategory(memories);
    var sorted = Object.keys(groups).sort(function(a, b) {
      return groups[b].length - groups[a].length;
    });

    el.innerHTML = sorted.map(function(cat) {
      return renderCard(cat, groups[cat]);
    }).join('');
  }

  function groupByCategory(memories) {
    var groups = {};
    memories.forEach(function(m) {
      var cat = JMD.categorizeMemory(m);
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(m);
    });
    return groups;
  }

  function renderCard(cat, items) {
    var def = JMD.CATEGORY_DEFS[cat] || JMD.CATEGORY_DEFS.other;
    return '<div class="cat-card">' +
      '<div class="cat-card-header" onclick="JMD.toggleCatCard(this)">' +
        '<div class="cat-card-left">' +
          '<div class="cat-icon" style="background:' + def.bg + ';color:' + def.color + '">' + def.icon + '</div>' +
          '<span class="cat-label" style="color:' + def.color + '">' + cat.toUpperCase() + '</span>' +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:8px">' +
          '<span class="cat-count">' + items.length + '</span>' +
          '<span class="cat-chevron">\u25BC</span>' +
        '</div>' +
      '</div>' +
      '<div class="cat-items">' + items.map(renderCatItem).join('') + '</div>' +
    '</div>';
  }

  function renderCatItem(m) {
    var hc = JMD.heatColorCSS(m.heat);
    var tags = (m.tags || []).map(function(t) {
      return '<span class="cat-mem-tag">' + JMD.escHtml(t) + '</span>';
    }).join('');

    return '<div class="cat-mem" onclick="JMD.toggleCatItem(event, this)">' +
      '<div class="cat-mem-header">' +
        '<span class="tl-type ' + (m.store_type || 'episodic') + '" style="font-size:7px">' + (m.store_type || 'episodic').slice(0, 4) + '</span>' +
        '<span style="font-size:10px;color:' + hc + '">' + m.heat.toFixed(2) + '</span>' +
        '<span style="font-size:9px;color:rgba(255,255,255,0.2)">' + JMD.timeAgo(m.created_at) + '</span>' +
      '</div>' +
      '<div class="cat-mem-content">' + JMD.escHtml(m.content) + '</div>' +
      '<div class="cat-mem-detail">' +
        'Domain: ' + (m.domain || '\u2014') + ' \u00b7 Importance: ' + (m.importance || 0).toFixed(2) +
        '<div class="cat-mem-tags">' + tags + '</div>' +
      '</div>' +
    '</div>';
  }

  JMD.toggleCatCard = function(header) {
    var items = header.nextElementSibling;
    items.classList.toggle('open');
    header.querySelector('.cat-chevron').classList.toggle('open');
  };

  JMD.toggleCatItem = function(e, item) {
    e.stopPropagation();
    item.querySelector('.cat-mem-content').classList.toggle('expanded');
    item.querySelector('.cat-mem-detail').classList.toggle('open');
  };

  JMD.on('data:refresh', function(data) {
    if (JMD.state.activeView === 'categories') renderCategories(data);
  });
  JMD.on('state:activeView', function(e) {
    if (e.value === 'categories' && JMD.state.lastData) renderCategories(JMD.state.lastData);
  });
})();
