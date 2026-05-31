// Cortex — Chain Panel
// Opens a side panel showing a Mermaid flowchart DAG for node chain analysis.
// Triggered by JUG.emit('chain:open', {id, label}).
(function () {
  var BG = '#0d1117', ACCENT = '#00d4ff';
  var _root = null, _svgHost = null, _titleEl = null, _metaEl = null;
  var _depthSel = null, _typeSel = null, _stateEl = null;
  var _current = { id: null, label: '' };
  var _mermaidReady = false;
  var _renderSeq = 0;

  function ensureMermaid() {
    if (_mermaidReady) return true;
    if (typeof window.mermaid === 'undefined') return false;
    window.mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      securityLevel: 'strict',
      flowchart: { useMaxWidth: true, htmlLabels: false },
    });
    _mermaidReady = true;
    return true;
  }

  function build() {
    if (_root) return;
    _root = document.createElement('div');
    _root.id = 'chain-panel';
    _root.style.cssText = [
      'position:fixed', 'top:0', 'right:0', 'bottom:0', 'width:40%',
      'min-width:360px', 'max-width:680px', 'background:' + BG,
      'border-left:1px solid rgba(0,212,255,0.35)', 'z-index:400',
      'box-shadow:-8px 0 32px rgba(0,0,0,0.5)', 'display:none',
      'flex-direction:column', 'color:#c4d4dc',
      'font-family:-apple-system,Inter,system-ui,sans-serif',
    ].join(';');

    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:10px;'
      + 'padding:14px 16px;border-bottom:1px solid rgba(0,212,255,0.2)';
    _titleEl = document.createElement('div');
    _titleEl.style.cssText = 'flex:1;font-weight:600;font-size:13px;color:'
      + ACCENT + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    _titleEl.textContent = 'Chain';
    var closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.setAttribute('aria-label', 'Close chain panel');
    closeBtn.style.cssText = 'background:transparent;border:none;color:' + ACCENT
      + ';font-size:16px;cursor:pointer;line-height:1;padding:4px';
    closeBtn.addEventListener('click', close);
    header.appendChild(_titleEl);
    header.appendChild(closeBtn);

    var controls = document.createElement('div');
    controls.style.cssText = 'display:flex;gap:12px;align-items:center;'
      + 'padding:10px 16px;border-bottom:1px solid rgba(0,212,255,0.12);font-size:11px';
    _depthSel = mkSelect('Depth',
      [1, 2, 3, 4, 5, 6].map(function (d) { return { v: d, t: 'Depth ' + d }; }), 2);
    _typeSel = mkSelect('Type', [
      { v: 'causal', t: 'Causal' },
      { v: 'impact', t: 'Impact' },
      { v: 'call', t: 'Call' },
    ], 0);
    _depthSel.addEventListener('change', refetch);
    _typeSel.addEventListener('change', refetch);
    controls.appendChild(labelWrap('Depth', _depthSel));
    controls.appendChild(labelWrap('Type', _typeSel));

    _metaEl = document.createElement('div');
    _metaEl.style.cssText = 'padding:6px 16px;font-size:10px;color:#7a8e9c;'
      + 'border-bottom:1px solid rgba(0,212,255,0.08);min-height:1.4em';

    _svgHost = document.createElement('div');
    _svgHost.style.cssText = 'flex:1;overflow:auto;padding:16px;'
      + 'display:flex;align-items:flex-start;justify-content:center';

    _stateEl = document.createElement('div');
    _stateEl.style.cssText = 'padding:24px 16px;text-align:center;'
      + 'color:#7a8e9c;font-size:12px';

    _root.appendChild(header);
    _root.appendChild(controls);
    _root.appendChild(_metaEl);
    _root.appendChild(_stateEl);
    _root.appendChild(_svgHost);
    document.body.appendChild(_root);
  }

  function mkSelect(name, opts, defIdx) {
    var s = document.createElement('select');
    s.setAttribute('aria-label', name);
    s.style.cssText = 'background:#11202b;color:#c4d4dc;border:1px solid '
      + 'rgba(0,212,255,0.3);border-radius:3px;padding:3px 6px;font-size:11px';
    opts.forEach(function (o, i) {
      var el = document.createElement('option');
      el.value = o.v; el.textContent = o.t;
      if (i === defIdx) el.selected = true;
      s.appendChild(el);
    });
    return s;
  }
  function labelWrap(text, sel) {
    var wrap = document.createElement('label');
    wrap.style.cssText = 'display:flex;align-items:center;gap:5px;color:#7a8e9c';
    var span = document.createElement('span');
    span.textContent = text;
    wrap.appendChild(span);
    wrap.appendChild(sel);
    return wrap;
  }

  function showState(msg, isError) {
    _stateEl.style.display = 'block';
    _stateEl.style.color = isError ? '#FF8080' : '#7a8e9c';
    _stateEl.textContent = msg;
    _svgHost.innerHTML = '';
  }
  function clearState() { _stateEl.style.display = 'none'; }

  function open(payload) {
    if (!payload || !payload.id) return;
    build();
    _current.id = payload.id;
    _current.label = payload.label || payload.id;
    _titleEl.textContent = 'Chain: ' + _current.label;
    _root.style.display = 'flex';
    refetch();
  }

  function close() {
    if (_root) _root.style.display = 'none';
  }

  function refetch() {
    if (!_current.id) return;
    var depth = _depthSel.value, type = _typeSel.value;
    var seq = ++_renderSeq;
    _metaEl.textContent = '';
    showState('Loading chain…', false);
    var url = '/api/graph/chain?id=' + encodeURIComponent(_current.id)
      + '&depth=' + encodeURIComponent(depth)
      + '&type=' + encodeURIComponent(type);
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (seq !== _renderSeq) return;   // superseded by a newer request
        if (data.error) { showState(data.error, true); return; }
        if (!data.mermaid) { showState('No chain for this node.', false); return; }
        renderMermaid(data, seq);
      })
      .catch(function (err) {
        if (seq !== _renderSeq) return;
        showState('Failed to load chain: ' + err.message, true);
      });
  }

  function renderMermaid(data, seq) {
    if (!ensureMermaid()) { showState('Mermaid not loaded.', true); return; }
    var meta = data.node_count + ' nodes · ' + data.edge_count + ' edges';
    if (data.truncated) meta += ' · truncated (depth/size cap)';
    _metaEl.textContent = meta;
    var graphId = 'chain-svg-' + seq;
    Promise.resolve()
      .then(function () { return window.mermaid.render(graphId, data.mermaid); })
      .then(function (out) {
        if (seq !== _renderSeq) return;
        clearState();
        _svgHost.innerHTML = (out && out.svg) || '';
      })
      .catch(function (err) {
        if (seq !== _renderSeq) return;
        showState('Render error: ' + (err && err.message || err), true);
      });
  }

  // Esc closes the panel.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && _root && _root.style.display !== 'none') close();
  });

  function attach() {
    if (!window.JUG || !JUG.on) { setTimeout(attach, 60); return; }
    JUG.on('chain:open', open);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
