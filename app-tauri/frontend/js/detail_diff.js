// Cortex Neural Graph — Diff Modal Viewer
// GitHub-style unified diff display with line numbers
(function() {
  var modal = null;
  var diffCache = {};

  function init() {
    modal = document.getElementById('diff-modal');
    if (!modal) return;

    modal.querySelector('.diff-modal-close').addEventListener('click', hide);
    modal.querySelector('.diff-modal-backdrop').addEventListener('click', hide);

    window.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) hide();
    });

    // Delegate clicks on "See diff" buttons — always try git diff first
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('.tool-diff-btn');
      if (!btn) return;
      showFileDiff(btn.dataset.file, btn.dataset.hasInline === '1');
    });
  }

  // ── Show inline diff from parsed tool capture ──

  function showInlineDiff(file) {
    var el = document.querySelector('.tool-inline-diff[data-file]');
    if (!el) return;
    var oldStr = decodeStr(el.dataset.old || '');
    var newStr = decodeStr(el.dataset.new || '');
    var lines = buildUnifiedDiff(oldStr, newStr);
    renderModal(shortName(file), 'Inline change', lines, false);
  }

  // ── Show file diff from git, fallback to inline ──

  function showFileDiff(file, hasInline) {
    var name = shortName(file);
    if (diffCache[file]) {
      renderFromGit(name, diffCache[file]);
      return;
    }
    renderModal(name, 'Loading...', [], false);
    show();
    var url = '/api/file-diff?name=' + encodeURIComponent(file);
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
      diffCache[file] = data;
      // If git found nothing but we have inline data, use that
      if (data.diff_type === 'none' && hasInline) {
        showInlineDiff(file);
        return;
      }
      renderFromGit(name, data);
    }).catch(function() {
      if (hasInline) { showInlineDiff(file); return; }
      renderModal(name, 'Could not load diff', [], false);
    });
  }

  function renderFromGit(name, data) {
    var labels = {
      uncommitted: 'Working-tree changes',
      staged:      'Staged changes',
      last_commit: 'Last commit that touched this file',
      new_file:    'New file — full content as additions',
      unchanged:   'Unchanged — HEAD content',
      deleted:     'Deleted — last-known content',
      untracked:   'Untracked new file — full content',
      none:        'File not found in repo or history',
    };
    var subtitle = labels[data.diff_type] || data.diff_type || 'Diff';
    if (data.reason) subtitle += ' — ' + data.reason;

    if (!data.lines || !data.lines.length) {
      // No line data — render an explicit empty state but keep the subtitle
      // honest so the user knows *why* there's nothing to show.
      renderModal(name, subtitle, [], false);
      return;
    }
    renderModal(name, subtitle, data.lines, data.truncated);
  }

  // ── Unified diff from old/new strings ──

  function buildUnifiedDiff(oldStr, newStr) {
    var oldLines = oldStr.split('\n');
    var newLines = newStr.split('\n');
    var result = [];
    var lcs = computeLCS(oldLines, newLines);
    var oi = 0, ni = 0, li = 0;

    while (oi < oldLines.length || ni < newLines.length) {
      if (li < lcs.length && oi < oldLines.length && ni < newLines.length &&
          oldLines[oi] === lcs[li] && newLines[ni] === lcs[li]) {
        result.push({ text: ' ' + oldLines[oi], type: 'ctx' });
        oi++; ni++; li++;
      } else if (oi < oldLines.length && (li >= lcs.length || oldLines[oi] !== lcs[li])) {
        result.push({ text: '-' + oldLines[oi], type: 'del' });
        oi++;
      } else if (ni < newLines.length) {
        result.push({ text: '+' + newLines[ni], type: 'add' });
        ni++;
      }
    }
    return result;
  }

  function computeLCS(a, b) {
    var m = a.length, n = b.length;
    // Limit to avoid freezing on huge diffs
    if (m > 200 || n > 200) return simpleLCS(a, b);
    var dp = [];
    for (var i = 0; i <= m; i++) { dp[i] = []; for (var j = 0; j <= n; j++) dp[i][j] = 0; }
    for (var i = 1; i <= m; i++) {
      for (var j = 1; j <= n; j++) {
        dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
      }
    }
    var result = [], i = m, j = n;
    while (i > 0 && j > 0) {
      if (a[i-1] === b[j-1]) { result.unshift(a[i-1]); i--; j--; }
      else if (dp[i-1][j] > dp[i][j-1]) i--;
      else j--;
    }
    return result;
  }

  function simpleLCS(a, b) {
    // Fast fallback: just find common lines in order
    var result = [], bi = 0;
    for (var ai = 0; ai < a.length && bi < b.length; ai++) {
      for (var j = bi; j < b.length; j++) {
        if (a[ai] === b[j]) { result.push(a[ai]); bi = j + 1; break; }
      }
    }
    return result;
  }

  // ── Render ──

  function renderModal(filename, subtitle, lines, truncated) {
    if (!modal) return;
    modal.querySelector('.diff-modal-filename').textContent = filename;
    modal.querySelector('.diff-modal-subtitle').textContent = subtitle;

    var body = modal.querySelector('.diff-modal-body');
    if (!lines || !lines.length) {
      body.innerHTML = '<div class="diff-empty">' + esc(subtitle) + '</div>';
      show();
      return;
    }

    var h = '<table class="diff-table"><tbody>';
    var oldNum = 0, newNum = 0;
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      var cls = 'diff-line-' + ln.type;
      if (ln.type === 'hunk') {
        var nums = ln.text.match(/@@ -(\d+).*\+(\d+)/);
        if (nums) { oldNum = parseInt(nums[1]) - 1; newNum = parseInt(nums[2]) - 1; }
        h += '<tr class="' + cls + '"><td class="diff-ln"></td><td class="diff-ln"></td>' +
          '<td class="diff-sign"></td><td class="diff-code">' + esc(ln.text) + '</td></tr>';
      } else if (ln.type === 'del') {
        oldNum++;
        h += '<tr class="' + cls + '"><td class="diff-ln">' + oldNum + '</td><td class="diff-ln"></td>' +
          '<td class="diff-sign">-</td><td class="diff-code">' + esc(stripPrefix(ln.text)) + '</td></tr>';
      } else if (ln.type === 'add') {
        newNum++;
        h += '<tr class="' + cls + '"><td class="diff-ln"></td><td class="diff-ln">' + newNum + '</td>' +
          '<td class="diff-sign">+</td><td class="diff-code">' + esc(stripPrefix(ln.text)) + '</td></tr>';
      } else {
        oldNum++; newNum++;
        h += '<tr class="' + cls + '"><td class="diff-ln">' + oldNum + '</td><td class="diff-ln">' + newNum + '</td>' +
          '<td class="diff-sign"></td><td class="diff-code">' + esc(stripPrefix(ln.text)) + '</td></tr>';
      }
    }
    if (truncated) {
      h += '<tr class="diff-line-hunk"><td class="diff-ln"></td><td class="diff-ln"></td>' +
        '<td class="diff-sign"></td><td class="diff-code">... diff truncated</td></tr>';
    }
    h += '</tbody></table>';
    body.innerHTML = h;
    show();
  }

  function stripPrefix(text) {
    if (!text) return '';
    if (text[0] === '+' || text[0] === '-' || text[0] === ' ') return text.substring(1);
    return text;
  }

  function show() { if (modal) modal.classList.add('open'); }
  function hide() { if (modal) modal.classList.remove('open'); }

  function shortName(path) {
    if (!path) return '';
    var parts = path.replace(/^["']|["']$/g, '').split('/');
    return parts.length <= 2 ? parts.join('/') : parts.slice(-2).join('/');
  }

  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }

  function decodeStr(s) {
    // Decode HTML entities in the correct order: &amp; last to prevent double-unescaping
    return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&amp;/g, '&');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    requestAnimationFrame(init);
  }

  JUG._diff = { show: showFileDiff, hide: hide };
})();
