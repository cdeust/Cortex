"""Graph cache and discussion-page builders for the standalone server.

Extracted from ``http_standalone.py`` to keep that file inside the
project-mandated 300-line ceiling. The module owns:

* graph-cache state (lock, domain-hub id map, roster fingerprint)
* the PHASE STATE MACHINE driving the progressive graph build
  (L0 domains → L1 setup → L2 tools → L3 files → L4 discussions
  → L5 memories → L6:<proj> per-project symbols → L6_CROSS)
* ``_kick_background_build`` — the background-thread builder
* ``get_graph_response`` — cache read, returns partial data while
  build is in progress, never re-kicks a running build
* ``get_phase_payload`` — per-phase nodes/edges delta for the
  ``/api/graph/phase`` append-only client loader
* ``build_discussions_response`` — paginated discussion listing
* ``build_discussion_detail`` — single-session detail
* ``parse_discussion_params`` / ``parse_graph_query`` — query-string parsers
* ``extract_domain_hub_ids`` — domain key → node id extraction

All I/O stays behind the existing infrastructure imports; the only
layer-relevant addition is that this module lives in ``server/`` and
composes ``handlers/workflow_graph`` + ``core/graph_builder_discussions``,
which matches the rules for server → handlers/core wiring.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from mcp_server.server.http_standalone_state import (
    CONVERSATIONS_CACHE_TTL,
    get_cached_conversations_state,
    set_cached_conversations_state,
)

_cached_domain_hub_ids: dict[str, str] = {}

_graph_cache: dict | None = None
_graph_cache_ts: float = 0.0
_graph_build_lock = threading.Lock()
# Fingerprint of the ap_graphs roster at the time of the last build.
# When it changes (a new project just finished indexing) the cache is
# invalidated so the next request rebuilds and the user sees the new
# symbols appear live.
_graph_roster_fingerprint: tuple = ()

# Build progress — updated by the background builder, read by the
# ``/api/graph/progress`` endpoint so the WASM client can show a
# progress bar instead of a silent spinner.
# ── Build state machine ──
#
# Each phase has an explicit READY flag. A phase is published only
# after every phase it depends on is READY. The client re-fetches
# ``/api/graph`` only when ``phase_seq`` increments, so it never sees
# a cache that lists an edge whose endpoint node belongs to a not-yet
# published phase.
#
# Phase dependency graph:
#
#   L0 (domains)         ← no prerequisites
#   L1 (skills/hooks/…)  ← L0 ready
#   L2 (tool_hubs)       ← L1 ready  (tool_hubs belong to a domain
#                                     via in_domain edges that
#                                     reference the domain node)
#   L3 (files)           ← L2 ready  (files attach to tool hubs)
#   L4 (discussions)     ← L3 ready  (discussion→file edges)
#   L5 (memories)        ← L0 ready  (memory→domain only)
#   L6 (AST symbols)     ← L3 ready  (symbol→file defined_in edges)
#   L6 edges             ← L6 ready  (all symbols first, then edges)
#
# The publish function below refuses to publish a phase whose
# prerequisites aren't satisfied — that makes rendering order safe
# at the STATE level, not at the render level.
PHASES = {
    "L0": {"deps": [], "ready": False, "label": "L0 domains"},
    "L1": {"deps": ["L0"], "ready": False, "label": "L1 Claude setup"},
    "L2": {"deps": ["L1"], "ready": False, "label": "L2 tools"},
    "L3": {"deps": ["L2"], "ready": False, "label": "L3 files"},
    "L4": {"deps": ["L3"], "ready": False, "label": "L4 discussions"},
    "L5": {"deps": ["L0"], "ready": False, "label": "L5 memories"},
    # L6 phases are added dynamically per project at build start:
    #   "L6:<proj_name>"  → that project's AST symbols + intra-project edges
    #   "L6_CROSS"        → cross-project symbol edges (deps = all L6:<proj>)
}

_build_progress: dict = {
    "phase": "idle",
    "phase_seq": 0,  # increments on every state transition
    "pct": 0.0,
    "message": "",
    "baseline_ready": False,
    "full_ready": False,
    "node_count": 0,
    "edge_count": 0,
    "started_at": 0.0,
    "elapsed": 0.0,
    "phases": {k: v["ready"] for k, v in PHASES.items()},
}
_build_progress_lock = threading.Lock()


def parse_graph_query(path: str) -> dict:
    """Parse ``/api/graph`` query string into domain/batch/batch_size."""
    result: dict = {"domain_filter": None, "batch": 0, "batch_size": 0}
    if "?" not in path:
        return result
    for p in path.split("?", 1)[1].split("&"):
        if p.startswith("domain="):
            result["domain_filter"] = p[7:]
        elif p.startswith("batch="):
            try:
                result["batch"] = int(p[6:])
            except ValueError:
                pass
        elif p.startswith("batch_size="):
            try:
                result["batch_size"] = int(p[11:])
            except ValueError:
                pass
    return result


def parse_discussion_params(path: str) -> dict:
    """Parse ``/api/discussions`` query string."""
    result: dict = {"project": None, "batch": 0, "batch_size": 500}
    if "?" not in path:
        return result
    for p in path.split("?", 1)[1].split("&"):
        if p.startswith("project="):
            result["project"] = p[8:]
        elif p.startswith("batch="):
            try:
                result["batch"] = int(p[6:])
            except ValueError:
                pass
        elif p.startswith("batch_size="):
            try:
                result["batch_size"] = int(p[11:])
            except ValueError:
                pass
    return result


def extract_domain_hub_ids(nodes: list[dict]) -> dict[str, str]:
    """Map domain label → node id across workflow-graph nodes."""
    hub_ids: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "domain" or node.get("kind") == "domain":
            domain_key = node.get("label") or node.get("domain") or ""
            if domain_key:
                hub_ids[domain_key] = node["id"]
    return hub_ids


def _compute_memory_vitals(store) -> dict:
    """Aggregate consolidation-stage counts, mean heat, and store-type split."""
    memories = store.get_hot_memories(min_heat=0.0, limit=0)
    stages: dict[str, int] = {}
    heats: list[float] = []
    episodic = 0
    semantic = 0
    for m in memories:
        s = m.get("consolidation_stage", "labile")
        stages[s] = stages.get(s, 0) + 1
        heats.append(m.get("heat", 0))
        if m.get("store_type") == "episodic":
            episodic += 1
        elif m.get("store_type") == "semantic":
            semantic += 1
    return {
        "consolidation_pipeline": stages,
        "mean_heat": round(sum(heats) / max(len(heats), 1), 4),
        "total_memories": len(memories),
        "episodic": episodic,
        "semantic": semantic,
    }


def _session_counts_from_profiles(profiles: dict) -> dict[str, int]:
    """Extract per-domain session counts from a profiles.json payload."""
    out: dict[str, int] = {}
    for did, ddata in (profiles.get("domains") or {}).items():
        out[did] = ddata.get("sessionCount", 0)
    return out


def _roster_fingerprint() -> tuple:
    """Return a tuple describing the current ap_graphs roster
    (``(path, size, mtime)`` for each graph directory). When this
    tuple changes — a new project has been indexed externally — the
    visualisation cache is invalidated so the next request rebuilds
    and the user sees the new symbols appear live."""
    from mcp_server.infrastructure.ap_bridge import resolve_graph_paths

    fp: list[tuple] = []
    for p in resolve_graph_paths():
        try:
            st = os.stat(p)
            fp.append((p, int(st.st_mtime), int(st.st_size)))
        except OSError:
            continue
    return tuple(fp)


def get_build_progress() -> dict:
    with _build_progress_lock:
        snap = dict(_build_progress)
        if snap.get("started_at"):
            snap["elapsed"] = time.monotonic() - snap["started_at"]
    return snap


def _set_progress(**kw) -> None:
    with _build_progress_lock:
        _build_progress.update(kw)


# Per-phase node/edge buffers. ``_merge`` writes into here in addition
# to the cumulative ``_graph_cache``. The ``/api/graph/phase`` endpoint
# returns ``_phase_payloads[key]`` so the client APPENDS the phase's
# deltas to its scene instead of rebuilding. Once a phase is READY its
# payload is immutable — no more writes land in it.
_phase_payloads: dict[str, dict] = {
    k: {"nodes": [], "edges": []}
    for k in (
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    )
}


def _register_phase(key: str, deps: list[str], label: str) -> None:
    """Add a dynamic phase at build time (per-project L6 phases +
    cross-project edges phase). Idempotent — if the phase already
    exists its deps/label are overwritten and ready is reset."""
    PHASES[key] = {"deps": list(deps), "ready": False, "label": label}
    _phase_payloads[key] = {"nodes": [], "edges": []}
    with _build_progress_lock:
        _build_progress.setdefault("phases", {})[key] = False


def get_phase_payload(key: str) -> dict:
    spec = PHASES.get(key)
    pl = _phase_payloads.get(key, {"nodes": [], "edges": []})
    return {
        "phase": key,
        "ready": bool(spec and spec["ready"]),
        "deps": spec["deps"] if spec else [],
        "nodes": pl.get("nodes", []),
        "edges": pl.get("edges", []),
    }


def _phase_deps_satisfied(phase_key: str) -> bool:
    """Return True iff every prerequisite phase of ``phase_key`` is
    already ``ready``. The build worker calls this before publishing a
    phase so the cache never contains an edge whose endpoint node
    lives in an unpublished phase."""
    spec = PHASES.get(phase_key)
    if not spec:
        return True
    return all(PHASES[d]["ready"] for d in spec["deps"])


def _mark_phase_ready(phase_key: str) -> None:
    """Flip the phase's ``ready`` flag and bump ``phase_seq`` so the
    client knows there's a new consistent snapshot to pull."""
    if phase_key not in PHASES:
        return
    PHASES[phase_key]["ready"] = True
    with _build_progress_lock:
        _build_progress["phase_seq"] = _build_progress.get("phase_seq", 0) + 1
        _build_progress["phases"] = {k: v["ready"] for k, v in PHASES.items()}


def _kick_background_build(store, domain_filter: str | None) -> None:
    """Spawn the two-stage background builder at most once. Stage 1
    (baseline, no AST) finishes in ~5 s and becomes the cached graph
    immediately. Stage 2 (AST sweep) runs afterwards and replaces
    the cache when it completes. Idempotent — the build lock
    collapses overlapping calls."""
    if not _graph_build_lock.acquire(blocking=False):
        return

    def _run():
        global _graph_roster_fingerprint

        def _merge(new_nodes, new_edges, stage, pct, message, phase_key=None, **flags):
            """Append ``new_nodes`` + ``new_edges`` into the cumulative
            cache AND into the phase-scoped buffer so the client can
            either fetch the whole cache (``/api/graph``) or pull
            only this phase's delta (``/api/graph/phase?name=<key>``).

            Dedupes per phase — new_nodes/new_edges that were already
            seen in a previous publish for the same phase are dropped.
            """
            global _graph_cache, _graph_cache_ts, _cached_domain_hub_ids
            cur = (
                _graph_cache["data"]
                if _graph_cache
                else {"nodes": [], "edges": [], "links": [], "meta": {}}
            )
            seen_n = {n.get("id") for n in cur.get("nodes", [])}
            seen_e = {
                (e.get("source"), e.get("target"), e.get("kind"))
                for e in cur.get("edges", [])
            }
            for n in new_nodes:
                nid = n.get("id")
                if nid and nid not in seen_n:
                    cur["nodes"].append(n)
                    seen_n.add(nid)
            for e in new_edges:
                key = (e.get("source"), e.get("target"), e.get("kind"))
                if key not in seen_e:
                    cur["edges"].append(e)
                    seen_e.add(key)
            cur["links"] = cur["edges"]
            cur.setdefault("meta", {})
            cur["meta"]["stage"] = stage
            cur["meta"]["node_count"] = len(cur["nodes"])
            cur["meta"]["edge_count"] = len(cur["edges"])
            cur["meta"]["schema"] = "workflow_graph.v1"
            # Per-kind tallies for the sidebar legend. Without these the
            # browser reads `meta.domain_count || 0` → always 0. Compute
            # from the cumulative nodes array so the counts stay exact
            # across phase appends.
            kind_counts: dict[str, int] = {}
            for _n in cur["nodes"]:
                k = _n.get("kind") or _n.get("type") or ""
                kind_counts[k] = kind_counts.get(k, 0) + 1
            cur["meta"]["domain_count"] = kind_counts.get("domain", 0)
            cur["meta"]["memory_count"] = kind_counts.get("memory", 0)
            # "Entity" in the legend covers every non-domain, non-memory
            # knowledge node (files, symbols, tools, commands, agents,
            # skills, hooks, discussions, MCPs). Compute as the sum.
            cur["meta"]["entity_count"] = (
                len(cur["nodes"])
                - kind_counts.get("domain", 0)
                - kind_counts.get("memory", 0)
            )
            cur["meta"]["counts"] = kind_counts
            # Also append into the per-phase delta buffer so the
            # client can ``GET /api/graph/phase?name=<key>`` and
            # append exactly this phase's new content to its live
            # scene instead of re-fetching the whole graph.
            if phase_key and phase_key in _phase_payloads:
                buf = _phase_payloads[phase_key]
                buf_seen_n = {n.get("id") for n in buf["nodes"]}
                for n in new_nodes:
                    if n.get("id") and n["id"] not in buf_seen_n:
                        buf["nodes"].append(n)
                        buf_seen_n.add(n["id"])
                buf_seen_e = {
                    (e.get("source"), e.get("target"), e.get("kind"))
                    for e in buf["edges"]
                }
                for e in new_edges:
                    key = (e.get("source"), e.get("target"), e.get("kind"))
                    if key not in buf_seen_e:
                        buf["edges"].append(e)
                        buf_seen_e.add(key)
            _graph_cache = {"data": cur, "domain_filter": domain_filter}
            _graph_cache_ts = time.monotonic()
            _cached_domain_hub_ids = extract_domain_hub_ids(cur["nodes"])
            _set_progress(
                phase=stage,
                pct=pct,
                message=message,
                node_count=len(cur["nodes"]),
                edge_count=len(cur["edges"]),
                **flags,
            )

        try:
            from mcp_server.handlers.workflow_graph import (
                build_workflow_graph,
            )

            _graph_roster_fingerprint = _roster_fingerprint()
            _set_progress(
                phase="starting",
                pct=0.01,
                message="loading layer definitions…",
                started_at=time.monotonic(),
                baseline_ready=False,
                full_ready=False,
                node_count=0,
                edge_count=0,
            )

            # Seed the cache fresh so the per-layer _merge writes land
            # on an empty graph.
            global _graph_cache
            _graph_cache = {
                "data": {"nodes": [], "edges": [], "links": [], "meta": {}},
                "domain_filter": domain_filter,
            }
            # Reset per-phase state so a rebuild starts clean — phases
            # flip ready→pending and buffers empty. Otherwise stale L6
            # nodes from a prior run leak into the new publish and the
            # client's dedup masks missing content.
            # NOTE: per-project L6 phases (added dynamically later)
            # will be registered fresh by _register_phase, which also
            # resets their ready flags — so we only need to flip the
            # FIXED phases here.
            for _k in list(PHASES):
                PHASES[_k]["ready"] = False
            for _k in list(_phase_payloads):
                _phase_payloads[_k]["nodes"].clear()
                _phase_payloads[_k]["edges"].clear()
            # Drop dynamic L6 phases from the previous run — they'll
            # be re-added below after graph_paths is resolved.
            for _k in list(PHASES):
                if _k.startswith("L6:") or _k == "L6_CROSS":
                    PHASES.pop(_k, None)
                    _phase_payloads.pop(_k, None)
            with _build_progress_lock:
                _build_progress["phase_seq"] = 0
                _build_progress["phases"] = {k: False for k in PHASES}
            # ── Per-layer streaming build ──
            # Each layer is published the instant its data is ready:
            #   L0  domains (the hubs)
            #   L1  Claude-Code setup: skills, hooks, commands, agents
            #   L2  tools (tool_hub nodes)
            #   L3  files (+ tool→file, command→file, discussion→file)
            #   L4  discussions
            #   L5  memories
            #   L6  AST symbols — streamed per project, per batch of 200
            # Ordering matches the user's requested reveal.
            # L0 + L1 + L2 + L3 + L4 + L5 all come from one
            # ``build_workflow_graph`` call; we can't easily partition
            # those. So we run baseline first (fast — a few seconds)
            # and merge the whole thing, then tag the phase.
            saved_flag = os.environ.get("CORTEX_ENABLE_AP")
            os.environ.pop("CORTEX_ENABLE_AP", None)
            baseline = build_workflow_graph(
                store,
                domain_filter=domain_filter,
                stage="full",
            )
            if saved_flag is not None:
                os.environ["CORTEX_ENABLE_AP"] = saved_flag

            # Partition baseline nodes by kind so we can publish one
            # layer at a time with a small delay — the client sees the
            # graph grow: domains → L1 → L2 → L3 → L4 → L5.
            by_kind: dict[str, list] = {}
            for n in baseline.get("nodes", []):
                by_kind.setdefault(n.get("kind") or "", []).append(n)
            edges_all = baseline.get("edges", [])
            node_ids_in_cache: set[str] = set()

            def _edges_for(node_ids: set[str]):
                """Return all edges both of whose endpoints are already
                in the cache — avoids publishing an edge before its
                target node is visible."""
                out = []
                for e in edges_all:
                    sid = (
                        e.get("source").get("id")
                        if isinstance(e.get("source"), dict)
                        else e.get("source")
                    )
                    tid = (
                        e.get("target").get("id")
                        if isinstance(e.get("target"), dict)
                        else e.get("target")
                    )
                    if sid in node_ids and tid in node_ids:
                        out.append(e)
                return out

            LAYER_ORDER = [
                ("L0", "L0 domains", ["domain"], 0.05),
                ("L1", "L1 setup", ["skill", "hook", "command", "agent", "mcp"], 0.10),
                ("L2", "L2 tools", ["tool_hub"], 0.14),
                ("L3", "L3 files", ["file"], 0.18),
                ("L4", "L4 discussions", ["discussion"], 0.22),
                # Entities publish alongside memories: the only edge they
                # carry is ``about_entity`` (MEMORY → ENTITY), so both
                # endpoints must land in the same phase or ``_edges_for``
                # drops the edge for lack of a visible target.
                ("L5", "L5 memories", ["memory", "entity"], 0.28),
            ]
            for phase_key, label, kinds, pct in LAYER_ORDER:
                # State-machine gate: block until every prerequisite
                # phase is ``ready``. Guarantees the cache never
                # publishes this phase's nodes/edges before its
                # parents exist.
                if not _phase_deps_satisfied(phase_key):
                    continue
                layer_nodes = []
                for k in kinds:
                    layer_nodes.extend(by_kind.get(k, []))
                for n in layer_nodes:
                    node_ids_in_cache.add(n.get("id"))
                layer_edges = _edges_for(node_ids_in_cache)
                # Only add the NEW edges this layer introduces.
                already_published = (
                    _graph_cache["data"].get("edges", []) if _graph_cache else []
                )
                already_keys = {
                    (e.get("source"), e.get("target"), e.get("kind"))
                    for e in already_published
                }
                new_edges = [
                    e
                    for e in layer_edges
                    if (e.get("source"), e.get("target"), e.get("kind"))
                    not in already_keys
                ]
                flags = (
                    {"baseline_ready": phase_key == "L5"} if phase_key == "L5" else {}
                )
                _merge(
                    layer_nodes,
                    new_edges,
                    stage=label,
                    pct=pct,
                    message=(
                        f"{label}: +{len(layer_nodes)} nodes (+{len(new_edges)} edges)"
                    ),
                    phase_key=phase_key,
                    **flags,
                )
                # Mark this phase as ``ready`` in the state machine
                # — the next phase (and the client's next fetch) can
                # now safely depend on these nodes existing.
                _mark_phase_ready(phase_key)
                time.sleep(0.1)

            # L6 — AST per project, per 200-symbol batch.
            from mcp_server.core.workflow_graph_palette import (
                SYMBOL_COLOR_DEFAULT,
                SYMBOL_COLORS,
            )
            from mcp_server.core.workflow_graph_schema import (
                NodeIdFactory,
                edge_provenance_defaults,
            )
            from mcp_server.infrastructure.ap_bridge import (
                is_enabled as _ap_enabled,
                resolve_graph_paths,
            )
            from mcp_server.infrastructure.workflow_graph_source_ast import (
                WorkflowGraphASTSource,
            )

            if not _ap_enabled():
                _set_progress(
                    phase="full_ready",
                    pct=1.0,
                    message=f"ready: {len(baseline.get('nodes', []))} nodes "
                    "(AP disabled)",
                    full_ready=True,
                )
                return

            # File-path → file-id map for DEFINED_IN edge resolution.
            file_id_by_path: dict[str, str] = {}
            for n in baseline.get("nodes", []):
                if n.get("kind") == "file":
                    p = n.get("path") or ""
                    fid = n.get("id")
                    if p and fid:
                        file_id_by_path[p] = fid
                        parts = p.split("/")
                        for i in range(1, len(parts)):
                            file_id_by_path.setdefault("/".join(parts[i:]), fid)

            ast_source = WorkflowGraphASTSource()
            graph_paths = resolve_graph_paths()
            total = max(len(graph_paths), 1)
            import hashlib
            import json as _json
            from pathlib import Path as _Path

            _BATCH = 200

            # ── Per-project AST cache ──
            # AP parses tree-sitter once per project and writes the
            # result into LadybugDB at ``~/.cortex/ap_graphs/<proj>/graph``.
            # Cortex then queries AP to pull the symbols + edges back out
            # for visualization. When nothing has changed in the underlying
            # graph files, the second-query result is identical — so we
            # cache it to disk and short-circuit the AP round-trip entirely.
            #
            # Key = SHA-256 of the graph directory's (path, size, mtime)
            # triples for every file inside. The instant any AP file
            # changes (re-index happened) the key differs and we refetch.
            _CACHE_DIR = _Path.home() / ".claude" / "methodology" / "ast_cache"
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

            def _graph_signature(gp_: str) -> str:
                root = _Path(gp_)
                if not root.exists():
                    return ""
                h = hashlib.sha256()
                # Walk deterministically so the signature is stable.
                for f in sorted(root.rglob("*")):
                    if not f.is_file():
                        continue
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    rel = str(f.relative_to(root))
                    h.update(rel.encode())
                    h.update(str(st.st_size).encode())
                    h.update(str(int(st.st_mtime)).encode())
                return h.hexdigest()[:16]

            def _cache_path(proj_name_: str) -> _Path:
                return _CACHE_DIR / f"{proj_name_}.json"

            def _cache_load(proj_name_: str, sig_: str):
                p = _cache_path(proj_name_)
                if not p.is_file() or not sig_:
                    return None
                try:
                    data = _json.loads(p.read_text())
                except Exception:
                    return None
                if data.get("signature") != sig_:
                    return None
                return data.get("symbols") or [], data.get("edges") or []

            def _cache_store(
                proj_name_: str, sig_: str, syms_: list, edgs_: list
            ) -> None:
                if not sig_:
                    return
                try:
                    _cache_path(proj_name_).write_text(
                        _json.dumps(
                            {
                                "signature": sig_,
                                "symbols": syms_,
                                "edges": edgs_,
                            }
                        )
                    )
                except Exception:
                    pass

            async def _load_with_timeout(gp_):
                # No timeout — large codebases legitimately take minutes
                # to parse via tree-sitter. Dropping projects silently
                # leaves the graph missing their symbols.
                syms = await ast_source._load_symbols_async(gp_, [])
                edgs = await ast_source._load_edges_async(gp_, [])
                return syms, edgs

            # L6 runs ONE PHASE PER PROJECT so the graph grows
            # project-by-project: finish indexing project A → publish
            # its symbol nodes + intra-project edges as phase
            # ``L6:A`` → client appends → next project. Cross-project
            # edges (rare: an ``imports`` pointing at a symbol that
            # lives in a different project's AST) are batched into
            # ``L6_CROSS`` at the very end when every project phase
            # is ready.
            _proj_names: list[str] = []
            for gp in graph_paths:
                pn = str(gp).rsplit("/", 3)[-2] if "/" in str(gp) else str(gp)
                _proj_names.append(pn)
                _register_phase(
                    f"L6:{pn}",
                    deps=["L3"],
                    label=f"L6 {pn} symbols",
                )
            _register_phase(
                "L6_CROSS",
                deps=[f"L6:{pn}" for pn in _proj_names],
                label="L6 cross-project edges",
            )

            # Track which symbols exist per-project so we can route
            # each edge into the right phase. An edge is "intra" iff
            # both endpoints are symbols indexed in THIS project.
            proj_symbol_ids: dict[str, set] = {pn: set() for pn in _proj_names}
            cross_edges: list[dict] = []

            for i, gp in enumerate(graph_paths):
                proj_name = _proj_names[i]
                phase_key = f"L6:{proj_name}"
                if not _phase_deps_satisfied(phase_key):
                    continue  # waiting for L3 — shouldn't happen here

                # Tight coupling with AP: if the underlying LadybugDB
                # graph hasn't changed (signature match), we already
                # know the answer — load from disk, skip the AP call.
                sig = _graph_signature(gp)
                cached = _cache_load(proj_name, sig)
                if cached is not None:
                    syms, edgs = cached
                    _set_progress(
                        phase=f"L6 {i + 1}/{total} {proj_name}",
                        pct=0.30 + 0.65 * ((i + 1) / total),
                        message=f"{proj_name}: cached ({len(syms)} symbols)",
                    )
                else:
                    try:
                        syms, edgs = ast_source._loop_owner.run(_load_with_timeout(gp))
                    except Exception as exc:
                        print(
                            f"[cortex] L6 project {proj_name} skipped: "
                            f"{type(exc).__name__}: {exc}",
                            file=sys.stderr,
                        )
                        _set_progress(
                            phase=f"L6 {i + 1}/{total} {proj_name}",
                            pct=0.30 + 0.65 * ((i + 1) / total),
                            message=f"{proj_name}: error — {type(exc).__name__}",
                        )
                        _mark_phase_ready(phase_key)
                        continue
                    # Persist for the next run.
                    _cache_store(proj_name, sig, list(syms), list(edgs))

                # Each symbol belongs to ITS PROJECT's domain — not the
                # global hub. The L0 phase emits domain ids as
                # ``domain:<kebab-case-label>`` (see
                # ``shared.project_ids.domain_id_from_label``); we match
                # that slugging here so symbol→domain routing lines up
                # with the existing domain nodes in the cache.
                from mcp_server.shared.project_ids import (
                    domain_id_from_label,
                )

                proj_slug = domain_id_from_label(proj_name) or proj_name
                proj_domain_id = f"domain:{proj_slug}"

                proj_nodes: list[dict] = []
                proj_edges: list[dict] = []

                # Every AST-indexed file is also a REAL file that can
                # be read/edited by Claude tools — same entity as an
                # L3 file. If L3 didn't see this file (never touched
                # during a tool call), emit it as a project-scoped
                # file node here so the symbol has a parent to attach
                # to and the file appears in the domain's file ring.
                ap_file_paths: set[str] = set()
                for sym in syms:
                    fp_ = sym.get("file_path") or ""
                    if fp_:
                        ap_file_paths.add(fp_)
                for fp_ in ap_file_paths:
                    if file_id_by_path.get(fp_):
                        continue
                    fid = NodeIdFactory.file_id(fp_)
                    file_id_by_path[fp_] = fid
                    # Also register every path-tail variant so the
                    # later symbol → file lookup still works when AP
                    # and L3 disagree on absolute vs relative paths.
                    parts = fp_.split("/")
                    for i in range(1, len(parts)):
                        file_id_by_path.setdefault("/".join(parts[i:]), fid)
                    proj_nodes.append(
                        {
                            "id": fid,
                            "kind": "file",
                            "type": "file",
                            "label": fp_.rsplit("/", 1)[-1],
                            "path": fp_,
                            "domain_id": proj_domain_id,
                            "domain": proj_slug,
                        }
                    )
                    # Bind the file to its domain so L3-layout places
                    # it in the domain's file ring.
                    proj_edges.append(
                        {
                            "source": fid,
                            "target": proj_domain_id,
                            "kind": "in_domain",
                            "type": "in_domain",
                            "weight": 1.0,
                        }
                    )

                for sym in syms:
                    qn = sym.get("qualified_name") or ""
                    fp = sym.get("file_path") or ""
                    if not qn:
                        continue
                    sid = NodeIdFactory.symbol_id(fp, qn)
                    proj_symbol_ids[proj_name].add(sid)
                    stype = str(sym.get("symbol_type") or "function")
                    proj_nodes.append(
                        {
                            "id": sid,
                            "kind": "symbol",
                            "type": "symbol",
                            "label": qn.rsplit("::", 1)[-1] or qn,
                            "color": SYMBOL_COLORS.get(stype, SYMBOL_COLOR_DEFAULT),
                            "path": fp,
                            "symbol_type": stype,
                            "domain_id": proj_domain_id,
                            "domain": proj_slug,
                        }
                    )
                    parent = file_id_by_path.get(fp)
                    if parent:
                        # Gap 6: shared provenance defaults.
                        di_conf, di_reason = edge_provenance_defaults("defined_in")
                        proj_edges.append(
                            {
                                "source": sid,
                                "target": parent,
                                "kind": "defined_in",
                                "type": "defined_in",
                                "weight": 1.0,
                                "confidence": di_conf,
                                "reason": di_reason,
                            }
                        )
                for e in edgs:
                    sf = e.get("src_file") or ""
                    sn = e.get("src_name") or ""
                    df = e.get("dst_file") or ""
                    dn = e.get("dst_name") or ""
                    if not df or not dn:
                        continue
                    did = NodeIdFactory.symbol_id(df, dn)
                    kind = e.get("kind") or "calls"
                    if kind == "imports":
                        sid = file_id_by_path.get(sf)
                        if not sid:
                            continue
                    else:
                        if not sf or not sn:
                            continue
                        sid = NodeIdFactory.symbol_id(sf, sn)
                    # Gap 6: single source-of-truth defaults.
                    conf, reason_v = edge_provenance_defaults(
                        kind,
                        ap_confidence=e.get("confidence"),
                        ap_reason=e.get("reason"),
                    )
                    edge = {
                        "source": sid,
                        "target": did,
                        "kind": kind,
                        "type": kind,
                        "weight": 1.0,
                        "confidence": conf,
                        "reason": reason_v,
                    }
                    # Intra-project iff both endpoints (where they are
                    # symbols) belong to THIS project. For `imports`
                    # the source is a file id, always "intra" once we
                    # see it here.
                    src_ok = kind == "imports" or sid in proj_symbol_ids[proj_name]
                    tgt_ok = did in proj_symbol_ids[proj_name]
                    if src_ok and tgt_ok:
                        proj_edges.append(edge)
                    else:
                        cross_edges.append(edge)

                # Stream this project's nodes in batches (smooth fade-in),
                # then its intra-project edges at the end.
                for bstart in range(0, len(proj_nodes), _BATCH):
                    chunk_nodes = proj_nodes[bstart : bstart + _BATCH]
                    _merge(
                        chunk_nodes,
                        [],
                        stage=f"L6 {i + 1}/{total} {proj_name}",
                        pct=0.30 + 0.65 * ((i + 1) / total),
                        message=(f"{proj_name}: +{len(chunk_nodes)} symbols"),
                        phase_key=phase_key,
                    )
                    time.sleep(0.02)
                # Intra-project edges land in the same project phase,
                # but only AFTER all its nodes — the client's dangling-
                # edge filter handles any slack.
                if proj_edges:
                    _merge(
                        [],
                        proj_edges,
                        stage=f"L6 {i + 1}/{total} {proj_name}",
                        pct=0.30 + 0.65 * ((i + 1) / total),
                        message=(f"{proj_name}: +{len(proj_edges)} AST edges"),
                        phase_key=phase_key,
                    )
                _mark_phase_ready(phase_key)

            # Cross-project edges — deps on every L6:<proj> phase.
            if not _phase_deps_satisfied("L6_CROSS"):
                return
            for bstart in range(0, len(cross_edges), 2000):
                chunk = cross_edges[bstart : bstart + 2000]
                _merge(
                    [],
                    chunk,
                    stage="L6 cross-edges",
                    pct=min(0.99, 0.95 + 0.04 * (bstart / max(len(cross_edges), 1))),
                    message=(
                        f"cross-project edges: +{len(chunk)} "
                        f"({bstart + len(chunk)}/{len(cross_edges)})"
                    ),
                    phase_key="L6_CROSS",
                )
                time.sleep(0.05)
            _mark_phase_ready("L6_CROSS")

            # Done.
            cur = _graph_cache["data"]
            counts = cur["meta"].get("counts") or {}
            counts["symbols"] = sum(
                1 for n in cur["nodes"] if n.get("kind") == "symbol"
            )
            counts["ast_edges"] = sum(
                1
                for e in cur["edges"]
                if (e.get("kind") or "")
                in ("defined_in", "calls", "imports", "member_of")
            )
            # Knowledge-graph entities + their MEMORY→ENTITY links
            # (ADR-0046 Gap 10 wiring). Counted at the finalisation step
            # so the stat panel's ``entities`` and
            # ``memory_entity_edges`` fields stay in sync with what the
            # renderer actually shows.
            counts["entities"] = sum(
                1 for n in cur["nodes"] if n.get("kind") == "entity"
            )
            counts["memory_entity_edges"] = sum(
                1 for e in cur["edges"] if (e.get("kind") or "") == "about_entity"
            )
            cur["meta"]["counts"] = counts
            _set_progress(
                phase="full_ready",
                pct=1.0,
                message=(
                    f"ready: {len(cur['nodes'])} nodes ({counts['symbols']} symbols)"
                ),
                full_ready=True,
                node_count=len(cur["nodes"]),
                edge_count=len(cur["edges"]),
            )
        except Exception as exc:  # pragma: no cover
            print(f"[cortex] background build error: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            _set_progress(
                phase="error",
                message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            _graph_build_lock.release()

    threading.Thread(target=_run, name="cortex-graph-build", daemon=True).start()


def get_graph_response(store, path: str) -> dict:
    """Return whatever's in the cache instantly; never block.

    First visit on a fresh server: kicks off the background builder
    and returns an empty placeholder. The client shows a progress
    bar driven by ``/api/graph/progress`` and re-fetches this
    endpoint once ``baseline_ready`` or ``full_ready`` flips true.

    Tight coupling rule: we NEVER kick a rebuild if a build is
    currently running OR the last-completed cache matches the
    current roster fingerprint. Without this guard, the per-phase
    progress polling + /api/graph round-trips were racing into
    repeated rebuilds — each one restarting the AST loop from
    project 0. The only legitimate reason to re-kick is a roster
    change (a new project appeared).
    """
    global _graph_roster_fingerprint
    params = parse_graph_query(path)
    domain_filter = params["domain_filter"]
    current_fp = _roster_fingerprint()
    roster_changed = current_fp != _graph_roster_fingerprint
    build_in_progress = _graph_build_lock.locked()
    cache_has_data = bool(
        _graph_cache
        and _graph_cache.get("data")
        and _graph_cache.get("domain_filter") == domain_filter
    )

    # Never re-kick while a build is running — the background thread
    # owns the AST loop, and double-triggering it would reset all
    # phase state mid-stream.
    # Also never re-kick if we already have a completed graph whose
    # roster hasn't changed — it's still current.
    if build_in_progress or (cache_has_data and not roster_changed):
        if cache_has_data:
            return _graph_cache["data"]
        # Build running but no data yet — return placeholder.
        return {
            "nodes": [],
            "edges": [],
            "clusters": [],
            "meta": {
                "schema": "workflow_graph.v1",
                "node_count": 0,
                "edge_count": 0,
                "stage": "building",
                "progress": get_build_progress(),
            },
        }

    _kick_background_build(store, domain_filter)

    # If there's any cache at all (stale TTL or prior domain), return
    # it — better than an empty graph. Otherwise placeholder.
    if _graph_cache and _graph_cache.get("data"):
        return _graph_cache["data"]

    return {
        "nodes": [],
        "edges": [],
        "clusters": [],
        "meta": {
            "schema": "workflow_graph.v1",
            "node_count": 0,
            "edge_count": 0,
            "stage": "building",
            "progress": get_build_progress(),
        },
    }


def _get_cached_conversations() -> list[dict]:
    """Shared cache wrapper — refreshes via ``discover_conversations``."""
    cached, ts = get_cached_conversations_state()
    now = time.time()
    if cached is None or (now - ts) > CONVERSATIONS_CACHE_TTL:
        from mcp_server.infrastructure.scanner import discover_conversations

        cached = discover_conversations()
        set_cached_conversations_state(cached, now)
    return cached


def build_discussions_response(path: str) -> dict:
    """Paginated response for ``/api/discussions``."""
    from mcp_server.core.graph_builder_discussions import build_discussion_nodes

    params = parse_discussion_params(path)
    conversations = _get_cached_conversations()
    if params["project"]:
        conversations = [
            c for c in conversations if c.get("project") == params["project"]
        ]
    conversations = sorted(
        conversations,
        key=lambda c: c.get("startedAt") or "",
        reverse=True,
    )
    total = len(conversations)
    batch_size = max(1, params["batch_size"])
    batch = params["batch"]
    total_batches = max(1, (total + batch_size - 1) // batch_size)
    start = batch * batch_size
    end = start + batch_size
    page = conversations[start:end]
    nodes, edges = build_discussion_nodes(page, _cached_domain_hub_ids)
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total": total,
            "batch": batch,
            "batch_size": batch_size,
            "total_batches": total_batches,
        },
    }


def _find_session_file(session_id: str):
    """Whitelist scan of every project dir for ``<session_id>.jsonl``."""
    from mcp_server.infrastructure.config import CLAUDE_DIR

    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return None
    target = session_id + ".jsonl"
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / target
        if candidate.is_file():
            return candidate
    return None


def build_discussion_detail(session_id: str) -> dict:
    """Detail response for ``/api/discussion/<session_id>``."""
    from mcp_server.infrastructure.conversation_reader import (
        format_conversation_messages,
        read_full_conversation,
    )

    conversations = _get_cached_conversations()
    conv = next(
        (c for c in conversations if c.get("sessionId") == session_id),
        None,
    )
    if conv is None:
        return {"error": "Discussion not found", "sessionId": session_id}

    found_path = _find_session_file(session_id)
    if found_path is None:
        return {"error": "Session file not found", "sessionId": session_id}

    raw = read_full_conversation(str(found_path))
    messages = format_conversation_messages(raw)
    return {
        "sessionId": session_id,
        "project": conv.get("project"),
        "messages": messages,
        "startedAt": conv.get("startedAt"),
        "endedAt": conv.get("endedAt"),
        "duration": conv.get("duration"),
        "turnCount": conv.get("turnCount"),
    }
