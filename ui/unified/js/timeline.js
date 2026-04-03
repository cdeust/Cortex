// Cortex Neural Graph — Session Timeline
(function() {
  var panel = document.getElementById('timeline-panel');
  var toggle = document.getElementById('timeline-toggle');
  var isOpen = false;
  var sessions = [];

  if (!panel || !toggle) return;

  // ── Toggle ──
  toggle.addEventListener('click', function() {
    isOpen = !isOpen;
    if (isOpen) {
      panel.style.display = 'block';
      toggle.classList.add('active');
      fetchTimeline();
    } else {
      panel.style.display = 'none';
      toggle.classList.remove('active');
    }
  });

  // ── Fetch ──
  function fetchTimeline() {
    var domain = (JUG.state && JUG.state.domainFilter) || '';
    var url = '/api/timeline?days=30&limit=50';
    if (domain) url += '&domain=' + encodeURIComponent(domain);

    panel.innerHTML = '<div class="tl-header">Session Timeline</div><div class="tl-empty">Loading...</div>';

    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        sessions = data.sessions || [];
        render();
      })
      .catch(function() {
        panel.innerHTML = '<div class="tl-header">Session Timeline</div><div class="tl-empty">Failed to load timeline</div>';
      });
  }

  // ── Render ──
  function render() {
    var html = '<div class="tl-header">Session Timeline</div>';

    if (!sessions.length) {
      html += '<div class="tl-empty">No sessions found.<br>Memories need session_id to appear here.</div>';
      panel.innerHTML = html;
      return;
    }

    var lastDate = '';
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      var dateStr = formatDate(s.first_at);
      var timeStr = formatTime(s.first_at);

      // Date header
      if (dateStr !== lastDate) {
        html += '<div class="tl-date-header">' + esc(dateStr) + '</div>';
        lastDate = dateStr;
      }

      // Session card
      html += '<div class="tl-session" data-idx="' + i + '">';
      html += '<div class="tl-session-head">';
      html += '<span class="tl-session-time">' + esc(timeStr) + '</span>';
      html += '<span class="tl-session-count">' + s.memory_count + '</span>';
      html += '</div>';

      // Domain badges
      if (s.domains && s.domains.length) {
        html += '<div class="tl-session-meta">';
        for (var d = 0; d < s.domains.length; d++) {
          html += '<span class="tl-domain-badge">' + esc(s.domains[d]) + '</span>';
        }
        html += '</div>';
      }

      // Summary (shown when expanded)
      html += '<div class="tl-session-summary">' + esc(s.summary || '') + '</div>';

      // Memory list placeholder (loaded on expand)
      html += '<div class="tl-memories" data-session="' + esc(s.session_id) + '"></div>';
      html += '</div>';
    }

    panel.innerHTML = html;
    bindSessionClicks();
  }

  // ── Session expand/collapse ──
  function bindSessionClicks() {
    var cards = panel.querySelectorAll('.tl-session');
    for (var i = 0; i < cards.length; i++) {
      cards[i].addEventListener('click', handleSessionClick);
    }
  }

  function handleSessionClick(e) {
    var card = e.currentTarget;
    var wasExpanded = card.classList.contains('expanded');

    // Collapse all
    var all = panel.querySelectorAll('.tl-session.expanded');
    for (var i = 0; i < all.length; i++) all[i].classList.remove('expanded');

    if (wasExpanded) return;

    // Expand this one
    card.classList.add('expanded');
    var memContainer = card.querySelector('.tl-memories');
    if (memContainer && !memContainer.dataset.loaded) {
      loadSessionMemories(memContainer);
    }

    // Stop propagation so memory item clicks work
    e.stopPropagation();
  }

  // ── Load memories for a session ──
  function loadSessionMemories(container) {
    var sessionId = container.dataset.session;
    if (!sessionId) return;

    // Find session data
    var sess = null;
    for (var i = 0; i < sessions.length; i++) {
      if (sessions[i].session_id === sessionId) { sess = sessions[i]; break; }
    }

    // Use the summary info we already have — no extra fetch needed
    // The timeline API already gave us the session grouping
    container.dataset.loaded = '1';
    container.innerHTML = '<div class="tl-memory-item" style="justify-content:center"><span class="tl-memory-text" style="color:var(--text-dim)">Click memory nodes in the graph to explore this session</span></div>';

    // If we want detailed memory items, fetch from the session API
    fetch('/api/timeline?limit=1&domain=')
      .then(function() {
        // Build inline memory references from summary
        if (sess && sess.summary) {
          var parts = sess.summary.split(' | ');
          var html = '';
          for (var p = 0; p < parts.length; p++) {
            var dotClass = 'tl-memory-dot';
            html += '<div class="tl-memory-item" data-snippet="' + esc(parts[p]) + '">';
            html += '<div class="' + dotClass + '"></div>';
            html += '<span class="tl-memory-text">' + esc(parts[p]) + '</span>';
            html += '</div>';
          }
          if (html) container.innerHTML = html;
          bindMemoryClicks(container);
        }
      })
      .catch(function() {});
  }

  // ── Memory item clicks ──
  function bindMemoryClicks(container) {
    var items = container.querySelectorAll('.tl-memory-item');
    for (var i = 0; i < items.length; i++) {
      items[i].addEventListener('click', function(e) {
        e.stopPropagation();
        var snippet = this.dataset.snippet || '';
        if (snippet && JUG.state) {
          // Search for this memory in the graph
          JUG.state.searchQuery = snippet.substring(0, 30);
        }
      });
    }
  }

  // ── Refresh on domain change ──
  if (JUG && JUG.on) {
    JUG.on('state:domainFilter', function() {
      if (isOpen) fetchTimeline();
    });
  }

  // ── Helpers ──
  function formatDate(iso) {
    if (!iso) return 'Unknown';
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    } catch(e) { return iso.substring(0, 10); }
  }

  function formatTime(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    } catch(e) { return iso.substring(11, 16); }
  }

  function esc(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
})();
