"""Workflow graph builder — reduces heterogeneous Claude-surface events to
the canonical node/edge vocabulary in ``workflow_graph_schema``. Pure core,
no I/O; malformed inputs raise ``ValueError``.

Canonical input forms (see infrastructure.workflow_graph_source):
  tool_events:    {"tool", "file_path"|None, "domain", "count"}
  skill_paths:    {"name", "path", "domains": list[str]}  (empty -> global)
  hook_defs:      {"event", "matcher"|"", "command", "domain"|None}
  agent_events:   {"subagent_type", "domain", "count"}
  command_events: {"cmd", "cmd_hash", "domain", "count"}
  memories:       PG rows (id, domain, consolidation_stage, heat_base, content)
  discussions:    {"session_id", "domain", "title", "message_count"}

Post-file-finalisation relational ingest (discussion → file / tool_hub /
agent / command, skill / mcp usage) lives in
``workflow_graph_builder_relational`` so this module stays inside the
300-line ceiling.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from mcp_server.core.workflow_graph_builder_relational import (
    ingest_command_file,
    ingest_discussion_agent,
    ingest_discussion_command,
    ingest_discussion_file,
    ingest_discussion_tool,
    ingest_mcp_usage,
    ingest_skill_usage,
)
from mcp_server.core.workflow_graph_schema import (
    AGENT_COLOR,
    COMMAND_COLOR,
    DISCUSSION_COLOR,
    DOMAIN_COLOR,
    GLOBAL_DOMAIN_ID,
    HOOK_COLOR,
    MEMORY_STAGE_COLORS,
    SKILL_COLOR,
    TOOL_HUB_COLORS,
    EdgeKind,
    NodeIdFactory,
    NodeKind,
    ToolKind,
    WorkflowEdge,
    WorkflowNode,
    classify_primary_tool,
    primary_tool_color,
)

_TOOL_NAME_TO_ENUM = {t.value: t for t in ToolKind}
_TOOL_NAME_LOWER = {t.value.lower(): t for t in ToolKind}

# Scientific-measurement fields forwarded verbatim to memory nodes so
# the Knowledge / Board cards can render them without a second PG hop.
_MEMORY_SCIENTIFIC_KEYS = tuple(
    (
        "heat_base arousal emotional_valence dominant_emotion importance "
        "surprise_score confidence access_count useful_count replay_count "
        "reconsolidation_count plasticity stability excitability "
        "hippocampal_dependency schema_match_score schema_id separation_index "
        "interference_score encoding_strength hours_in_stage stage_entered_at "
        "last_accessed no_decay is_protected is_stale is_benchmark is_global "
        "store_type compression_level compressed"
    ).split()
)


def _require(rec: dict, key: str, ctx: str):
    if key not in rec or rec[key] is None:
        raise ValueError(f"{ctx}: missing key {key!r} in {rec!r}")
    return rec[key]


def _as_tool(name: str) -> ToolKind:
    if name in _TOOL_NAME_TO_ENUM:
        return _TOOL_NAME_TO_ENUM[name]
    low = name.lower()
    if low in _TOOL_NAME_LOWER:
        return _TOOL_NAME_LOWER[low]
    raise ValueError(f"unknown ToolKind: {name!r}")


class WorkflowGraphBuilder:
    """Reduce seven data sources to canonical (nodes, edges)."""

    def __init__(self) -> None:
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: list[WorkflowEdge] = []
        self._file_tool_counts: dict[str, Counter[ToolKind]] = defaultdict(Counter)
        self._file_domains: dict[str, set[str]] = defaultdict(set)
        self._file_timestamps: dict[str, dict[str, str | None]] = {}

    def build(
        self,
        tool_events,
        skill_paths,
        hook_defs,
        agent_events,
        command_events,
        memories,
        discussions,
        discussion_file_events=None,
        skill_usage_events=None,
        command_file_events=None,
        mcp_usage_events=None,
        discussion_tool_events=None,
        discussion_agent_events=None,
        discussion_command_events=None,
    ):
        self._ensure_domain(GLOBAL_DOMAIN_ID, "global")
        # Phase 1: node ingestion (self-bound).
        for events, fn in (
            (tool_events, self._ingest_tool_event),
            (skill_paths, self._ingest_skill),
            (hook_defs, self._ingest_hook),
            (agent_events, self._ingest_agent),
            (command_events, self._ingest_command),
            (memories, self._ingest_memory),
            (discussions, self._ingest_discussion),
        ):
            for ev in events or []:
                fn(ev)
        self._finalize_files()
        # Phase 2: relational edges (builder-bound helpers — see
        # ``workflow_graph_builder_relational``; all assume file nodes exist).
        for events, fn in (
            (discussion_file_events, ingest_discussion_file),
            (command_file_events, ingest_command_file),
            (skill_usage_events, ingest_skill_usage),
            (mcp_usage_events, ingest_mcp_usage),
            (discussion_tool_events, ingest_discussion_tool),
            (discussion_agent_events, ingest_discussion_agent),
            (discussion_command_events, ingest_discussion_command),
        ):
            for ev in events or []:
                fn(self, ev)
        return self._dedupe_and_link(self._nodes.values(), self._edges)

    # ── al-jabr: fill missing domain / classify file tool mix ─────────

    def _assign_domain(self, domain_id, known_project_roots=()):
        _ = known_project_roots
        if not domain_id:
            return GLOBAL_DOMAIN_ID
        if domain_id.startswith("domain:"):
            return domain_id
        return NodeIdFactory.domain_id(domain_id)

    # ── Node constructors ─────────────────────────────────────────────

    def _ensure_domain(self, domain_id, label=None):
        if domain_id not in self._nodes:
            self._nodes[domain_id] = WorkflowNode(
                id=domain_id,
                kind=NodeKind.DOMAIN,
                label=label or domain_id.replace("domain:", ""),
                color=DOMAIN_COLOR,
                domain_id=domain_id,
                size=5.0,
            )
        return domain_id

    def _build_tool_hubs(self, domain_id, active_tools):
        created = []
        for tool in active_tools:
            hub_id = NodeIdFactory.tool_hub_id(domain_id, tool)
            if hub_id in self._nodes:
                continue
            node = WorkflowNode(
                id=hub_id,
                kind=NodeKind.TOOL_HUB,
                label=tool.value,
                color=TOOL_HUB_COLORS[tool],
                domain_id=domain_id,
                size=2.5,
                tool=tool,
            )
            self._nodes[hub_id] = node
            self._edges.append(self._in_domain(hub_id, domain_id))
            created.append(node)
        return created

    @staticmethod
    def _in_domain(source, domain_id):
        return WorkflowEdge(source=source, target=domain_id, kind=EdgeKind.IN_DOMAIN)

    def _add_child(self, node_id, kind, label, color, domain_id, size, **extra):
        """Idempotent non-domain node + in_domain edge. Returns True if new."""
        if node_id in self._nodes:
            return False
        self._nodes[node_id] = WorkflowNode(
            id=node_id,
            kind=kind,
            label=label,
            color=color,
            domain_id=domain_id,
            size=size,
            **extra,
        )
        self._edges.append(self._in_domain(node_id, domain_id))
        return True

    # ── Ingest ────────────────────────────────────────────────────────

    def _ingest_tool_event(self, ev):
        tool = _as_tool(str(_require(ev, "tool", "tool_event")))
        dom = self._assign_domain(ev.get("domain"))
        self._ensure_domain(dom)
        self._build_tool_hubs(dom, [tool])
        path = ev.get("file_path")
        if not path:
            return
        count = int(ev.get("count") or 1)
        self._file_tool_counts[path][tool] += count
        self._file_domains[path].add(dom)
        self._track_file_timestamp(path, tool, ev)
        self._edges.append(
            WorkflowEdge(
                source=NodeIdFactory.tool_hub_id(dom, tool),
                target=NodeIdFactory.file_id(path),
                kind=EdgeKind.TOOL_USED_FILE,
                weight=float(count),
            )
        )

    def _track_file_timestamp(self, path: str, tool: ToolKind, ev: dict) -> None:
        """Accumulate per-file first_seen / last_accessed / last_modified.

        first_seen  = earliest access of any kind.
        last_accessed = latest access of any kind (incl. Read/Grep/Glob).
        last_modified = latest Edit or Write access only.
        """
        first_ts = ev.get("first_ts")
        last_ts = ev.get("last_ts")
        if not first_ts and not last_ts:
            return
        slot = self._file_timestamps.setdefault(
            path,
            {"first_seen": None, "last_accessed": None, "last_modified": None},
        )
        if first_ts and (slot["first_seen"] is None or first_ts < slot["first_seen"]):
            slot["first_seen"] = first_ts
        if last_ts and (
            slot["last_accessed"] is None or last_ts > slot["last_accessed"]
        ):
            slot["last_accessed"] = last_ts
        if tool in (ToolKind.EDIT, ToolKind.WRITE) and last_ts:
            if slot["last_modified"] is None or last_ts > slot["last_modified"]:
                slot["last_modified"] = last_ts

    def _finalize_files(self):
        for path, tc in self._file_tool_counts.items():
            cluster = classify_primary_tool(dict(tc))
            fid = NodeIdFactory.file_id(path)
            doms = sorted(self._file_domains[path])
            if not doms:
                raise ValueError(f"file {path} has no domain membership")
            ts = self._file_timestamps.get(path, {})
            self._nodes[fid] = WorkflowNode(
                id=fid,
                kind=NodeKind.FILE,
                label=path.rsplit("/", 1)[-1] or path,
                color=primary_tool_color(cluster),
                domain_id=doms[0],
                size=1.5,
                primary_cluster=cluster,
                path=path,
                extra_domain_ids=doms[1:],
                first_seen=ts.get("first_seen"),
                last_accessed=ts.get("last_accessed"),
                last_modified=ts.get("last_modified"),
            )
            for d in doms:
                self._edges.append(self._in_domain(fid, d))

    def _ingest_memory(self, mem):
        pg_id = _require(mem, "id", "memory")
        dom = self._assign_domain(mem.get("domain"))
        self._ensure_domain(dom)
        stage = mem.get("consolidation_stage") or mem.get("stage") or "episodic"
        heat = float(mem.get("heat") or mem.get("heat_base") or 0.0)
        content = mem.get("content") or ""
        tags = mem.get("tags") if isinstance(mem.get("tags"), list) else []
        science = {
            k: mem[k]
            for k in _MEMORY_SCIENTIFIC_KEYS
            if k in mem and mem[k] is not None
        }
        self._add_child(
            NodeIdFactory.memory_id(pg_id),
            NodeKind.MEMORY,
            content[:60].replace("\n", " ") or f"memory {pg_id}",
            MEMORY_STAGE_COLORS.get(stage, MEMORY_STAGE_COLORS["episodic"]),
            dom,
            1.0 + min(3.0, heat * 3.0),
            stage=stage,
            body=content[:4000] if content else None,
            heat=heat,
            tags=[str(t) for t in tags][:20],
            created_at=mem.get("created_at"),
            **science,
        )

    def _ingest_discussion(self, dc):
        sid = str(_require(dc, "session_id", "discussion"))
        dom = self._assign_domain(dc.get("domain"))
        self._ensure_domain(dom)
        mc = int(dc.get("message_count") or 0)
        self._add_child(
            f"discussion:{sid}",
            NodeKind.DISCUSSION,
            dc.get("title") or sid[:8],
            DISCUSSION_COLOR,
            dom,
            1.0 + min(3.0, mc * 0.02),
            session_id=sid,
            count=mc,
            started_at=dc.get("started_at"),
            last_activity=dc.get("last_activity"),
            duration_ms=dc.get("duration_ms"),
        )

    def _ingest_skill(self, sk):
        name = str(_require(sk, "name", "skill"))
        path = str(_require(sk, "path", "skill"))
        doms = [self._assign_domain(d) for d in (sk.get("domains") or [])] or [
            GLOBAL_DOMAIN_ID
        ]
        for d in doms:
            self._ensure_domain(d)
        node_id = NodeIdFactory.skill_id(name)
        self._add_child(
            node_id,
            NodeKind.SKILL,
            name,
            SKILL_COLOR,
            doms[0],
            2.0,
            path=path,
            extra_domain_ids=doms[1:],
            body=sk.get("body"),
        )
        for d in doms:
            self._edges.append(
                WorkflowEdge(
                    source=d,
                    target=node_id,
                    kind=EdgeKind.INVOKED_SKILL,
                )
            )

    def _ingest_hook(self, hk):
        event = str(_require(hk, "event", "hook"))
        cmd = str(_require(hk, "command", "hook"))
        dom = self._assign_domain(hk.get("domain"))
        self._ensure_domain(dom)
        node_id = NodeIdFactory.hook_id(event, cmd)
        matcher = hk.get("matcher") or ""
        label = f"{event}:{matcher}" if matcher else event
        if not self._add_child(
            node_id, NodeKind.HOOK, label, HOOK_COLOR, dom, 1.5, path=cmd, event=event
        ):
            return
        self._edges.append(
            WorkflowEdge(
                source=dom,
                target=node_id,
                kind=EdgeKind.TRIGGERED_HOOK,
                label=event,
            )
        )

    def _ingest_agent(self, ag):
        sub = str(_require(ag, "subagent_type", "agent"))
        dom = self._assign_domain(ag.get("domain"))
        self._ensure_domain(dom)
        self._build_tool_hubs(dom, [ToolKind.TASK])
        hub = NodeIdFactory.tool_hub_id(dom, ToolKind.TASK)
        node_id = NodeIdFactory.agent_id(dom, sub)
        count = int(ag.get("count") or 1)
        self._add_child(
            node_id,
            NodeKind.AGENT,
            sub,
            AGENT_COLOR,
            dom,
            2.0,
            subagent_type=sub,
            count=count,
        )
        self._edges.append(
            WorkflowEdge(
                source=hub,
                target=node_id,
                kind=EdgeKind.SPAWNED_AGENT,
                weight=float(count),
            )
        )

    def _ingest_command(self, cm):
        cmd = str(_require(cm, "cmd", "command"))
        h = str(_require(cm, "cmd_hash", "command"))
        dom = self._assign_domain(cm.get("domain"))
        self._ensure_domain(dom)
        self._build_tool_hubs(dom, [ToolKind.BASH])
        hub = NodeIdFactory.tool_hub_id(dom, ToolKind.BASH)
        node_id = NodeIdFactory.command_id(h)
        count = int(cm.get("count") or 1)
        if not self._add_child(
            node_id,
            NodeKind.COMMAND,
            cmd[:80],
            COMMAND_COLOR,
            dom,
            1.0 + min(3.0, count * 0.1),
            body=cmd,
            count=count,
            first_seen=cm.get("first_ts"),
            last_accessed=cm.get("last_ts"),
        ):
            return
        # Bash hub → command containment. Uses COMMAND_IN_HUB (not
        # TOOL_USED_FILE) so workflow_graph_panel.js renderToolHub's
        # "Files touched" counter isn't inflated by the command count.
        self._edges.append(
            WorkflowEdge(
                source=hub,
                target=node_id,
                kind=EdgeKind.COMMAND_IN_HUB,
                weight=float(count),
            )
        )

    # ── al-muqabala: dedupe by (src, tgt, kind); sum weights ──────────

    def _dedupe_and_link(
        self, nodes: Iterable[WorkflowNode], edges: Iterable[WorkflowEdge]
    ):
        node_list = list(nodes)
        seen: dict[tuple[str, str, str], WorkflowEdge] = {}
        for e in edges:
            kv = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
            key = (e.source, e.target, kv)
            if key in seen:
                seen[key] = seen[key].model_copy(
                    update={"weight": seen[key].weight + e.weight}
                )
                continue
            seen[key] = e
        return node_list, list(seen.values())


__all__ = ["WorkflowGraphBuilder"]
