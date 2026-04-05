// Cortex Neural Graph — Discussion Detail & Conversation Modal
// Handles discussion-specific content in the detail panel
// Uses JUG._fmt (detail_format.js) for shared formatting utilities
(function() {

  // ── Detail panel content for discussion nodes ──

  function buildDiscussionDetail(data) {
    var h = '';

    // Timeline section
    h += '<div class="section-title">Timeline</div>';
    h += '<div class="disc-timeline">';
    if (data.startedAt) {
      h += '<div class="disc-timeline-row"><span>Started</span><span class="disc-val">' + formatTimestamp(data.startedAt) + '</span></div>';
    }
    if (data.duration) {
      h += '<div class="disc-timeline-row"><span>Duration</span><span class="disc-val">' + formatDuration(data.duration) + '</span></div>';
    }
    if (data.startedAt) {
      h += '<div class="disc-relative">' + relativeTime(data.startedAt) + '</div>';
    }
    h += '</div>';

    // Stats
    var stats = [];
    if (data.turnCount) stats.push('<span>' + data.turnCount + '</span> turns');
    if (data.messageCount) stats.push('<span>' + data.messageCount + '</span> messages');
    if (data.fileSize) stats.push('<span>' + formatFileSize(data.fileSize) + '</span>');
    if (stats.length) {
      h += '<div class="disc-stats">' + stats.join(' ') + '</div>';
    }

    // Tools used
    var tools = data.toolsUsed || data.tools || [];
    if (tools.length) {
      h += '<div class="section-title">Tools Used</div>';
      h += '<div class="disc-tools">';
      tools.forEach(function(t) {
        h += '<span class="disc-tool-badge">' + JUG._fmt.esc(t) + '</span>';
      });
      h += '</div>';
    }

    // Keywords
    var kws = data.keywords;
    if (typeof kws === 'string') {
      kws = kws.replace(/[{}']/g, '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    }
    if (kws && kws.length) {
      h += '<div class="section-title">Keywords</div>';
      var TC = JUG._tagColors;
      var s = TC['_default'];
      h += '<div class="tag-group-items">';
      kws.forEach(function(kw) {
        h += '<span class="detail-tag" style="color:' + s.color + ';border-color:' + s.border + ';background:' + s.bg + '">' + JUG._fmt.esc(kw) + '</span>';
      });
      h += '</div>';
    }

    // View Full Conversation button
    if (data.sessionId) {
      h += '<button class="disc-view-btn" data-session-id="' + JUG._fmt.esc(data.sessionId) + '">View Full Conversation</button>';
    }

    return h;
  }

  function formatFileSize(bytes) {
    if (!bytes) return '--';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return Math.round(bytes / 1024) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function relativeTime(iso) {
    var now = Date.now();
    var then = new Date(iso).getTime();
    var diff = Math.floor((now - then) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    if (diff < 2592000) return Math.floor(diff / 604800) + 'w ago';
    return Math.floor(diff / 2592000) + 'mo ago';
  }

  function formatDuration(ms) {
    if (!ms) return '--';
    var min = Math.floor(ms / 60000);
    if (min < 60) return min + ' min';
    return Math.floor(min / 60) + 'h ' + (min % 60) + 'min';
  }

  function formatTimestamp(iso) {
    if (!iso) return '--';
    var d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) +
           ' at ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  }

  // ── Conversation modal ──

  function openConversationModal(sessionId) {
    var modal = document.getElementById('conversation-modal');
    if (!modal) return;
    var body = modal.querySelector('.conv-modal-body');
    var title = modal.querySelector('.conv-modal-title');
    body.innerHTML = '<div class="conv-loading">Loading conversation...</div>';
    title.textContent = 'Session ' + sessionId.substring(0, 8) + '...';
    modal.classList.add('open');

    fetch('/api/discussion/' + sessionId)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        body.innerHTML = renderConversation(data.messages || [], data);
      })
      .catch(function(err) {
        body.innerHTML = '<div class="conv-error">Failed to load: ' + err.message + '</div>';
      });
  }

  function renderConversation(messages, meta) {
    var h = '<div class="conv-meta">';
    h += '<span>' + formatTimestamp(meta.startedAt) + '</span>';
    h += '<span>' + formatDuration(meta.duration) + '</span>';
    h += '<span>' + (meta.turnCount || messages.length) + ' turns</span>';
    h += '</div>';

    messages.forEach(function(msg) {
      var cls = msg.role === 'user' ? 'conv-msg-user' : 'conv-msg-assistant';
      h += '<div class="conv-msg ' + cls + '">';
      h += '<div class="conv-msg-role">' + JUG._fmt.esc(msg.role) + '</div>';
      if (msg.timestamp) {
        h += '<div class="conv-msg-time">' + new Date(msg.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) + '</div>';
      }
      var text = (msg.text || '').trim();
      h += '<div class="conv-msg-text">' + JUG._fmt.esc(text) + '</div>';
      if (msg.toolCalls && msg.toolCalls.length) {
        msg.toolCalls.forEach(function(tc) {
          h += '<details class="conv-tool-call">';
          h += '<summary>' + JUG._fmt.esc(tc.name || 'tool') + '</summary>';
          if (tc.input) h += '<pre class="conv-tool-io">' + JUG._fmt.esc(String(tc.input)) + '</pre>';
          h += '</details>';
        });
      }
      h += '</div>';
    });
    return h;
  }

  function closeConversationModal() {
    var modal = document.getElementById('conversation-modal');
    if (modal) modal.classList.remove('open');
  }

  // Wire modal close
  document.addEventListener('DOMContentLoaded', function() {
    var modal = document.getElementById('conversation-modal');
    if (!modal) return;
    var closeBtn = modal.querySelector('.conv-modal-close');
    var backdrop = modal.querySelector('.conv-modal-backdrop');
    if (closeBtn) closeBtn.addEventListener('click', closeConversationModal);
    if (backdrop) backdrop.addEventListener('click', closeConversationModal);
  });

  window.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeConversationModal();
  });

  // Export
  JUG._disc = {
    buildDiscussionDetail: buildDiscussionDetail,
    openConversationModal: openConversationModal,
    relativeTime: relativeTime,
    formatDuration: formatDuration,
  };
})();
