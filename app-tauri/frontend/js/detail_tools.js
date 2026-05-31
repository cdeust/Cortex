// Cortex Neural Graph — Tool Capture → Plain English
// Converts raw Claude Code tool output into human-readable summaries
(function() {

  function isToolCapture(text) {
    return /^#?\s*Tool:\s/i.test(text);
  }

  function parseCapture(text) {
    var r = { tool: '', file: '', command: '', oldStr: '', newStr: '' };
    text.split('\n').forEach(function(ln) {
      var l = ln.replace(/^#+\s*/, '').replace(/\*\*/g, '');
      if (/^Tool:\s*(.+)/i.test(l)) r.tool = RegExp.$1.trim();
      else if (/^File:\s*(.+)/i.test(l)) r.file = RegExp.$1.trim().replace(/^["'`]|["'`]$/g, '');
      else if (/^Command:\s*(.+)/i.test(l)) r.command = RegExp.$1.replace(/^`|`$/g, '').trim();
    });
    if (!r.file) { var fp = text.match(/"filePath":\s*"([^"]+)"/); if (fp) r.file = fp[1]; }
    var om = text.match(/"oldString":\s*"([\s\S]*?)(?:"\s*[,}])/);
    var nm = text.match(/"newString":\s*"([\s\S]*?)(?:"\s*[,}])/);
    if (om) r.oldStr = om[1].replace(/\\n/g, '\n').replace(/\\t/g, '  ').replace(/\\"/g, '"');
    if (nm) r.newStr = nm[1].replace(/\\n/g, '\n').replace(/\\t/g, '  ').replace(/\\"/g, '"');
    return r;
  }

  // ── Plain English generators per tool type ──

  function summarizeEdit(tc) {
    var parts = [];
    var fname = shortName(tc.file);
    parts.push('Made a code change to <b>' + fname + '</b>.');
    if (tc.oldStr && tc.newStr) {
      var oldLines = tc.oldStr.trim().split('\n').length;
      var newLines = tc.newStr.trim().split('\n').length;
      if (newLines > oldLines) {
        parts.push('Added ' + (newLines - oldLines) + ' new line' + (newLines - oldLines > 1 ? 's' : '') + '.');
      } else if (oldLines > newLines) {
        parts.push('Removed ' + (oldLines - newLines) + ' line' + (oldLines - newLines > 1 ? 's' : '') + '.');
      } else {
        parts.push('Modified ' + oldLines + ' line' + (oldLines > 1 ? 's' : '') + '.');
      }
      var what = describeCodeChange(tc.oldStr, tc.newStr);
      if (what) parts.push(what);
    }
    return parts;
  }

  function summarizeBash(tc) {
    var parts = [];
    var cmd = tc.command || '';
    if (/pytest|test/i.test(cmd)) parts.push('Ran the test suite.');
    else if (/pip install/i.test(cmd)) parts.push('Installed Python packages.');
    else if (/git\s+(commit|push|pull|merge|checkout)/i.test(cmd)) parts.push('Performed a git operation.');
    else if (/cd\s/i.test(cmd) && /&&/.test(cmd)) parts.push('Navigated to a directory and ran a command.');
    else if (/grep|rg|find/i.test(cmd)) parts.push('Searched through files.');
    else if (/curl|wget|fetch/i.test(cmd)) parts.push('Made a network request.');
    else if (/rm\s|delete/i.test(cmd)) parts.push('Deleted files.');
    else if (/mkdir/i.test(cmd)) parts.push('Created a directory.');
    else if (/python|node/i.test(cmd)) parts.push('Ran a script.');
    else parts.push('Executed a shell command.');
    return parts;
  }

  function summarizeRead(tc) {
    var fname = shortName(tc.file);
    return ['Read the file <b>' + fname + '</b> to understand its contents.'];
  }

  function summarizeWrite(tc) {
    var fname = shortName(tc.file);
    return ['Created or overwrote the file <b>' + fname + '</b>.'];
  }

  function summarizeGrep(tc) {
    return ['Searched for a pattern across the codebase.'];
  }

  function summarizeGeneric(tc) {
    var parts = [];
    if (tc.file) parts.push('Operated on <b>' + shortName(tc.file) + '</b>.');
    else parts.push('Performed an action.');
    return parts;
  }

  // ── Code change description ──

  function describeCodeChange(oldStr, newStr) {
    var oldTrimmed = oldStr.trim(), newTrimmed = newStr.trim();
    if (/^(import|from)\s/.test(oldTrimmed) || /^(import|from)\s/.test(newTrimmed)) {
      return 'Updated import statements.';
    }
    var oldFn = oldTrimmed.match(/(?:def|function|class)\s+(\w+)/);
    var newFn = newTrimmed.match(/(?:def|function|class)\s+(\w+)/);
    if (oldFn && newFn && oldFn[1] !== newFn[1]) {
      return 'Renamed <b>' + oldFn[1] + '</b> to <b>' + newFn[1] + '</b>.';
    }
    if (/=\s*["'\d]/.test(oldTrimmed) && /=\s*["'\d]/.test(newTrimmed)) {
      return 'Updated configuration values.';
    }
    return '';
  }

  // ── Renderer ──

  function renderToolCard(raw, esc) {
    var tc = parseCapture(raw);
    var tool = tc.tool.toLowerCase();
    var parts;
    if (tool.indexOf('edit') >= 0) parts = summarizeEdit(tc);
    else if (tool.indexOf('bash') >= 0) parts = summarizeBash(tc);
    else if (tool.indexOf('read') >= 0) parts = summarizeRead(tc);
    else if (tool.indexOf('write') >= 0) parts = summarizeWrite(tc);
    else if (tool.indexOf('grep') >= 0) parts = summarizeGrep(tc);
    else parts = summarizeGeneric(tc);

    var h = '<div class="section-title">What happened</div>';
    h += '<div class="tool-summary">';
    h += '<div class="tool-summary-icon">' + toolIcon(tool) + '</div>';
    h += '<div class="tool-summary-body">';
    for (var i = 0; i < parts.length; i++) {
      h += '<p class="tool-summary-line">' + parts[i] + '</p>';
    }
    if (tc.file) {
      h += '<div class="tool-summary-path">' + esc(shortName(tc.file)) + '</div>';
    }
    // See Diff button for edit/write tools with a file
    if (tc.file && (tool.indexOf('edit') >= 0 || tool.indexOf('write') >= 0)) {
      h += '<button class="tool-diff-btn" data-file="' + esc(tc.file) + '"';
      if (tc.oldStr || tc.newStr) {
        h += ' data-has-inline="1"';
      }
      h += '>See diff</button>';
    }
    h += '</div></div>';

    // Inline diff data for the modal (hidden, picked up by detail_diff.js)
    if (tc.oldStr || tc.newStr) {
      h += '<div class="tool-inline-diff" style="display:none"' +
        ' data-old="' + encodeStr(tc.oldStr) + '"' +
        ' data-new="' + encodeStr(tc.newStr) + '"' +
        ' data-file="' + esc(tc.file || '') + '"></div>';
    }
    return h;
  }

  function toolIcon(tool) {
    if (tool.indexOf('edit') >= 0) return '<span class="tool-icon tool-icon-edit">E</span>';
    if (tool.indexOf('bash') >= 0) return '<span class="tool-icon tool-icon-bash">&gt;</span>';
    if (tool.indexOf('read') >= 0) return '<span class="tool-icon tool-icon-read">R</span>';
    if (tool.indexOf('write') >= 0) return '<span class="tool-icon tool-icon-write">W</span>';
    if (tool.indexOf('grep') >= 0) return '<span class="tool-icon tool-icon-grep">S</span>';
    return '<span class="tool-icon tool-icon-default">?</span>';
  }

  function shortName(path) {
    if (!path) return '';
    var parts = path.replace(/^["']|["']$/g, '').split('/');
    return parts.length <= 2 ? parts.join('/') : parts.slice(-2).join('/');
  }

  function encodeStr(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  JUG._tools = { isToolCapture: isToolCapture, renderToolCard: renderToolCard };
})();
