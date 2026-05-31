// Cortex — Incremental leaves-first phase loader for the legacy force graph.
//
// User-requested visual: leaves at the perimeter draw first, paths to
// the centre fill in progressively. We honour that ordering whenever
// multiple phases are ready at once — but we don't make the user
// stare at an empty canvas while the build runs. As soon as ANY phase
// is ready we paint it; when several are ready in the same tick we
// prefer the leafier one. Net effect: the user sees SOMETHING within
// seconds, and the graph fills inward as outer phases arrive.
//
// Server side already exposes per-phase deltas:
//   GET /api/graph/progress       → { phases: {L0,…}, full_ready, … }
//   GET /api/graph/phase?name=<k> → { nodes, edges } for that phase only
//
// Client side: graph.js's JUG.appendGraphDelta dedupes nodes/edges by
// id and rAF-coalesces a single rebuild — so a burst of phase deltas
// yields one redraw per frame, not one per node. It also live-updates
// the sidebar counters from lastData.nodes (so the legend numbers are
// always correct, regardless of which phases have landed).
(function () {
  'use strict';

  if (typeof window.JUG === 'undefined') return;
  if (typeof JUG.appendGraphDelta !== 'function') {
    console.warn('[phase] JUG.appendGraphDelta missing — graph.js not loaded?');
    return;
  }

  var POLL_MS = 1500;
  var loaded = Object.create(null);
  var pending = false;

  function _setStatus(text) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = text;
  }

  // Higher rank = leafier = load first when several are ready in the
  // same tick. L6:<proj> and L6_CROSS are the leafiest (per-project
  // AST symbols + cross-project symbol edges); L0 is the trunk.
  function _rank(key) {
    if (key === 'L6_CROSS') return 100;
    if (key.indexOf('L6:') === 0) return 90;
    var n = parseInt(key.charAt(1), 10);
    return isFinite(n) ? n : -1;
  }

  // Phases that add no structural value to the graph view — skip them.
  // memory_entity_edges: 110K+ KG entity edges that flood the canvas
  // with a green cloud obscuring the structural galaxy layout.
  var SKIP = { memory_entity_edges: true, L5: true };

  function _readyKeys(phases) {
    var keys = [];
    for (var k in phases) {
      if (phases[k] && !loaded[k] && !SKIP[k]) keys.push(k);
    }
    keys.sort(function (a, b) { return _rank(b) - _rank(a); });
    return keys;
  }

  function _fetchPhase(name) {
    return fetch('/api/graph/phase?name=' + encodeURIComponent(name))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        var n = (d && d.nodes) || [];
        var e = (d && d.edges) || [];
        if (n.length || e.length) {
          JUG.appendGraphDelta(n, e);
          console.log('[phase] +' + name + ' nodes=' + n.length + ' edges=' + e.length);
        }
        loaded[name] = true;
      })
      .catch(function (err) {
        console.warn('[phase] fetch ' + name + ' failed:', err.message);
      });
  }

  function _hideLoader() {
    var el = document.getElementById('loading');
    if (!el || el.classList.contains('done')) return;
    el.classList.add('done');
    el.style.opacity = '0';
    el.style.pointerEvents = 'none';
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 600);
  }

  function _tick() {
    if (pending) return;
    pending = true;
    fetch('/api/graph/progress')
      .then(function (r) { return r.json(); })
      .then(function (p) {
        var keys = _readyKeys(p.phases || {});
        if (keys.length === 0) {
          var phase = p.phase || '';
          var pct = Math.round((p.pct || 0) * 100);
          _setStatus('Building · ' + phase + ' (' + pct + '%)');
          pending = false;
          if (!p.full_ready) setTimeout(_tick, POLL_MS);
          return;
        }
        // Fetch the leafiest ready phase first, sequentially. The for
        // loop below would race appendGraphDelta if we Promise.all'd —
        // we want one phase per redraw to give the force layout a
        // moment to settle before the next ring lands.
        var next = keys[0];
        _setStatus('Loading from edge inward · ' + next);
        _fetchPhase(next).then(function () {
          _hideLoader();
          pending = false;
          // Two animation frames between phases so the user perceives
          // the rings filling in instead of a single flash.
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              if (p.full_ready && _readyKeys(p.phases).length === 0) {
                _setStatus('Ready · ' + (JUG.state.lastData ? JUG.state.lastData.nodes.length : 0) + ' nodes');
              } else {
                _tick();
              }
            });
          });
        });
      })
      .catch(function (err) {
        console.warn('[phase] progress fetch failed:', err.message);
        pending = false;
        setTimeout(_tick, POLL_MS * 2);
      });
  }

  function _start() {
    _setStatus('Waiting for first phase…');
    console.log('[phase] incremental leaves-first loader active');
    _tick();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _start);
  } else {
    _start();
  }
})();
