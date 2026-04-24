// Cortex — Workflow Graph: per-kind detail-panel renderers.
// Each render<Kind>(body, n, ctx) mutates `body` via primitives from
// JUG._wfgPanelHelpers. Pure DOM composition, no I/O. Dispatch table
// lives at the bottom of this file (JUG._wfgRenderers).

(function () {
  function P() {
    return (window.JUG && window.JUG._wfgPanelHelpers) || {};
  }
  function H() {
    return (window.JUG && window.JUG._wfgHumanize) || {};
  }

  function renderDomain(body, n, ctx) {
    var p = P();
    p.renderCommon(body, n, ctx);
    var kinds = p.countNeighborsByKind(n, ctx);
    var s = p.section('Cloud contents');
    var order = [
      'tool_hub', 'file', 'skill', 'hook', 'agent',
      'command', 'memory', 'discussion',
    ];
    for (var i = 0; i < order.length; i++) {
      if (kinds[order[i]]) s.appendChild(p.row(order[i], kinds[order[i]]));
    }
    body.appendChild(s);
  }

  function renderToolHub(body, n, ctx) {
    var p = P();
    body.appendChild(p.row('Tool', n.tool || n.label));
    p.renderCommon(body, n, ctx);
    var weight = 0;
    var files = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      if (e.kind !== 'tool_used_file') return false;
      if (other.kind !== 'file') return false;
      weight += e.weight || 1;
      return true;
    });
    body.appendChild(p.row('Files touched', files.length));
    body.appendChild(p.row('Total uses', Math.round(weight)));
    p.renderNeighborList(body, 'Files accessed by this tool', files, ctx);
    var cmds = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_in_hub' && other.kind === 'command';
    });
    p.renderNeighborList(body, 'Commands in this hub', cmds, ctx);
  }

  function _renderFileIdentity(body, n) {
    var p = P();
    var h = H();
    if (n.path) body.appendChild(p.row('Path', n.path));
    if (n.primary_cluster) {
      var c = (h.primaryClusterLabel && h.primaryClusterLabel(n.primary_cluster))
        || n.primary_cluster;
      body.appendChild(p.row('How it was used', c));
    }
    if (n.first_seen)   body.appendChild(p.row('First seen',   p.humanDate(n.first_seen)));
    if (n.last_accessed) body.appendChild(p.row('Last access',  p.humanDate(n.last_accessed)));
    if (n.last_modified) body.appendChild(p.row('Last modified', p.humanDate(n.last_modified)));
  }

  function _renderFileDomains(body, n, ctx) {
    var p = P();
    if (n.extra_domain_ids && n.extra_domain_ids.length) {
      var s = p.section('Also in projects');
      n.extra_domain_ids.forEach(function (d) {
        s.appendChild(p.row('', p.domainLabel(ctx, d)));
      });
      body.appendChild(s);
    }
  }

  function _renderFileRelationships(body, n, ctx) {
    var p = P();
    var tools = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'tool_used_file' && other.kind === 'tool_hub';
    });
    p.renderNeighborList(body, 'Accessed by tools', tools, ctx);
    var defined = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'defined_in' && other.kind === 'symbol';
    });
    p.renderNeighborList(body, 'Symbols defined here', defined, ctx);
    var discs = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_touched_file' && other.kind === 'discussion';
    });
    p.renderNeighborList(body, 'Discussions involving this file', discs, ctx);
    var cmds = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_touched_file' && other.kind === 'command';
    });
    p.renderNeighborList(body, 'Commands that touched this file', cmds, ctx);
    var imps = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'imports';
    });
    p.renderNeighborList(body, 'Imports / imported by', imps, ctx);
  }

  function _renderFileDiffButton(body, n) {
    var p = P();
    if (n.primary_cluster !== 'edit_write' || !n.path) return;
    var ds = p.section('Diff');
    ds.appendChild(p.actionBtn('See diff against HEAD', function () {
      if (window.JUG && JUG._diff && typeof JUG._diff.show === 'function') {
        JUG._diff.show(n.path, false);
      } else {
        console.warn('[wfg] diff modal unavailable');
      }
    }));
    body.appendChild(ds);
  }

  function renderFile(body, n, ctx) {
    _renderFileIdentity(body, n);
    P().renderCommon(body, n, ctx);
    _renderFileDomains(body, n, ctx);
    _renderFileRelationships(body, n, ctx);
    _renderFileDiffButton(body, n);
  }

  function renderMemory(body, n, ctx) {
    var p = P();
    p.stageRows(n.stage).forEach(function (r) { body.appendChild(r); });
    if (n.heat != null) body.appendChild(p.heatRow(n.heat));
    if (n.created_at) body.appendChild(p.row('Created', p.humanDate(n.created_at)));
    p.renderCommon(body, n, ctx);
    if (n.tags && n.tags.length) {
      var tagWrap = p.section('Tags');
      var chips = p.el('div', 'wfg-panel__chips');
      n.tags.forEach(function (t) { chips.appendChild(p.tagChip(t)); });
      tagWrap.appendChild(chips);
      body.appendChild(tagWrap);
    }
    if (n.body) {
      var bs = p.section('What was remembered');
      bs.appendChild(p.preview(n.body, 4000));
      body.appendChild(bs);
    }
  }

  function _renderDiscussionMeta(body, n) {
    var p = P();
    if (n.session_id)    body.appendChild(p.row('Session',       n.session_id));
    if (n.count != null) body.appendChild(p.row('Messages',      n.count));
    if (n.started_at)    body.appendChild(p.row('Started',       p.humanDate(n.started_at)));
    if (n.last_activity) body.appendChild(p.row('Last activity', p.humanDate(n.last_activity)));
    if (n.duration_ms != null) body.appendChild(p.row('Duration', p.humanDuration(n.duration_ms)));
  }

  function _renderDiscussionRelationships(body, n, ctx) {
    var p = P();
    var touched = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_touched_file' && other.kind === 'file';
    });
    p.renderNeighborList(body, 'Files touched in session', touched, ctx);
    var usedTools = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_used_tool' && other.kind === 'tool_hub';
    });
    p.renderNeighborList(body, 'Tools used', usedTools, ctx);
    var ranCmds = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_ran_command' && other.kind === 'command';
    });
    p.renderNeighborList(body, 'Commands run', ranCmds, ctx);
    var spawnedAgents = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'discussion_spawned_agent' && other.kind === 'agent';
    });
    p.renderNeighborList(body, 'Sub-assistants spawned', spawnedAgents, ctx);
  }

  function _renderDiscussionOpenButton(body, n) {
    var p = P();
    if (!n.session_id) return;
    var ds = p.section('Conversation');
    ds.appendChild(p.actionBtn('View full conversation', function () {
      if (window.JUG && JUG._disc && typeof JUG._disc.openConversationModal === 'function') {
        JUG._disc.openConversationModal(n.session_id);
      } else {
        console.warn('[wfg] conversation modal unavailable');
      }
    }));
    body.appendChild(ds);
  }

  function renderDiscussion(body, n, ctx) {
    _renderDiscussionMeta(body, n);
    P().renderCommon(body, n, ctx);
    _renderDiscussionRelationships(body, n, ctx);
    _renderDiscussionOpenButton(body, n);
  }

  // ── renderSkill / renderHook / renderCommand / renderAgent ───────────
  function renderSkill(body, n, ctx) {
    var p = P();
    if (n.path) body.appendChild(p.row('File', n.path));
    p.renderCommon(body, n, ctx);
    if (n.body) {
      var bs = p.section('Definition');
      bs.appendChild(p.preview(n.body, 2000));
      body.appendChild(bs);
    }
  }

  function renderHook(body, n, ctx) {
    var p = P();
    if (n.event) body.appendChild(p.row('Event',   n.event));
    if (n.path)  body.appendChild(p.row('Command', n.path));
    p.renderCommon(body, n, ctx);
  }

  function renderCommand(body, n, ctx) {
    var p = P();
    if (n.count != null)  body.appendChild(p.row('Invocations',  n.count));
    if (n.first_seen)     body.appendChild(p.row('First seen',   p.humanDate(n.first_seen)));
    if (n.last_accessed)  body.appendChild(p.row('Last invoked', p.humanDate(n.last_accessed)));
    p.renderCommon(body, n, ctx);
    if (n.body) {
      var bs = p.section('Command line');
      bs.appendChild(p.preview(n.body, 1000));
      body.appendChild(bs);
    }
    var touched = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_touched_file' && other.kind === 'file';
    });
    p.renderNeighborList(body, 'Files this command touched', touched, ctx);
    var parentHub = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'command_in_hub' && other.kind === 'tool_hub';
    });
    p.renderNeighborList(body, 'Part of tool group', parentHub, ctx);
  }

  function renderAgent(body, n, ctx) {
    var p = P();
    if (n.subagent_type) body.appendChild(p.row('Sub-assistant type', n.subagent_type));
    if (n.count != null) body.appendChild(p.row('Invocations',        n.count));
    p.renderCommon(body, n, ctx);
  }

  function _renderSymbolIdentity(body, n, ctx) {
    var p = P();
    var h = H();
    if (n.symbol_type) {
      var t = (h.symbolTypeLabel && h.symbolTypeLabel(n.symbol_type)) || n.symbol_type;
      body.appendChild(p.row('Type', t));
    }
    if (n.path)  body.appendChild(p.row('File', n.path));
    if (n.label) body.appendChild(p.row('Name', n.label));
    p.renderCommon(body, n, ctx);
  }

  function _renderSymbolRelationships(body, n, ctx) {
    var p = P();
    var parents = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'defined_in' && other.kind === 'file' && isOut;
    });
    p.renderNeighborList(body, 'Defined in file', parents, ctx);
    var containers = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'member_of' && other.kind === 'symbol' && isOut;
    });
    p.renderNeighborList(body, 'Member of', containers, ctx);
    var members = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'member_of' && other.kind === 'symbol' && !isOut;
    });
    p.renderNeighborList(body, 'Methods / members', members, ctx);
    var callsOut = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'calls' && isOut;
    });
    p.renderNeighborList(body, 'Calls these symbols', callsOut, ctx);
    var callsIn = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'calls' && !isOut;
    });
    p.renderNeighborList(body, 'Called from', callsIn, ctx);
    var importedBy = p.collectNeighbors(n, ctx, function (e, isOut, other) {
      return e.kind === 'imports' && other.kind === 'file' && !isOut;
    });
    p.renderNeighborList(body, 'Imported by files', importedBy, ctx);
  }

  function renderSymbol(body, n, ctx) {
    _renderSymbolIdentity(body, n, ctx);
    _renderSymbolRelationships(body, n, ctx);
  }

  // ── Dispatch table ───────────────────────────────────────────────────
  var BY_KIND = {
    domain:     renderDomain,
    tool_hub:   renderToolHub,
    file:       renderFile,
    memory:     renderMemory,
    discussion: renderDiscussion,
    skill:      renderSkill,
    hook:       renderHook,
    command:    renderCommand,
    agent:      renderAgent,
    symbol:     renderSymbol,
  };

  window.JUG = window.JUG || {};
  window.JUG._wfgRenderers = { byKind: BY_KIND, get: function (k) { return BY_KIND[k] || null; } };
})();
