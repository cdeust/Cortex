"""HTTP endpoints for the domain-split execution-trace graph.

Live, no-snapshot serving of the four navigation levels:

    GET /api/trace/domains            -> L0 domain hubs
    GET /api/trace/sessions?domain=   -> L1 sessions + has_session edges
    GET /api/trace/chain?session=     -> L2 ordered prompt/action/file chain
    GET /api/trace/file?path=         -> L3 file drill (AST + impact + git)

Each reads live from JSONL / AP graph / git per request — nothing cached
to disk.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from mcp_server.server.http_standalone_response import (
    send_json_error,
    send_json_ok,
)


def _param(handler, key: str) -> str:
    qs = parse_qs(urlparse(handler.path).query)
    vals = qs.get(key)
    return unquote(vals[0]) if vals else ""


def serve_trace_domains(handler) -> None:
    """GET /api/trace/domains — collapsed domain hubs (L0)."""
    try:
        from mcp_server.infrastructure.trace_source import list_domains

        nodes = list_domains()
        send_json_ok(
            handler,
            {"nodes": nodes, "edges": [], "meta": {"schema": "trace.v1", "level": 0}},
        )
    except Exception as e:
        send_json_error(handler, e)


def serve_trace_sessions(handler) -> None:
    """GET /api/trace/sessions?domain=<domain:id> — sessions in a domain (L1)."""
    try:
        from mcp_server.infrastructure.trace_source import list_sessions

        domain = _param(handler, "domain")
        if not domain:
            send_json_ok(handler, {"nodes": [], "edges": [], "error": "missing domain"})
            return
        payload = list_sessions(domain)
        payload["meta"] = {"schema": "trace.v1", "level": 1, "domain": domain}
        send_json_ok(handler, payload)
    except Exception as e:
        send_json_error(handler, e)


def serve_trace_chain(handler) -> None:
    """GET /api/trace/chain?session=<sid> — ordered causal chain (L2)."""
    try:
        from mcp_server.core.session_trace import build_chain
        from mcp_server.infrastructure.trace_source import iter_session_events

        sid = _param(handler, "session")
        if not sid:
            send_json_ok(
                handler, {"nodes": [], "edges": [], "error": "missing session"}
            )
            return
        # ``since`` = chain steps the client already holds (live tail poll).
        # 0/absent → whole chain. Out-of-range → empty delta (dedup-safe).
        try:
            since = int(_param(handler, "since") or "0")
        except ValueError:
            since = 0
        events = iter_session_events(sid)
        payload = build_chain(events, sid, since=since)
        payload["meta"] = {
            "schema": "trace.v1",
            "level": 2,
            "session": sid,
            "event_count": len(events),
            "since": since,
        }
        send_json_ok(handler, payload)
    except Exception as e:
        send_json_error(handler, e)


def _git_history(path: str) -> dict:
    """Working-tree/last-commit diff + when-changed for one file."""
    try:
        from mcp_server.infrastructure.git_diff import (
            find_git_root,
            get_file_diff,
            resolve_file,
        )
        from mcp_server.server.http_file_diff import _git_root_for_name

        # Resolve the repo from the FILE's own path (graph nodes carry
        # absolute paths), not the server CWD — which is never a repo.
        root = _git_root_for_name(path, find_git_root)
        if root is None:
            return {"available": False}
        rel = resolve_file(path, root) or path
        diff = get_file_diff(rel, root)
        return {
            "available": True,
            "diff_type": diff.get("diff_type"),
            "lines": diff.get("lines", []),
            "truncated": diff.get("truncated", False),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "error": str(exc)}


def _git_versions(path: str, limit: int = 25) -> dict:
    """Full commit history for one file — the 'versioning' axis.

    Returns ``{available, versions:[{sha, date, author, subject}]}`` from
    ``git log`` scoped to the file (follows renames). Pure git, no AP — a
    reliable longitudinal view of how this file changed over time, to sit
    next to AP's static dependency direction and causal chains.
    """
    try:
        import subprocess

        from mcp_server.infrastructure.git_diff import find_git_root, resolve_file
        from mcp_server.server.http_file_diff import _git_root_for_name

        # Resolve the repo from the file's own path, not the server CWD.
        root = _git_root_for_name(path, find_git_root)
        if root is None:
            return {"available": False}
        rel = (resolve_file(path, root) or path or "").replace("\\", "/")
        # %x1f = unit separator (safe field delim); %x1e = record separator.
        fmt = "%h%x1f%aI%x1f%an%x1f%s%x1e"
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                "--follow",
                f"-n{int(limit)}",
                f"--format={fmt}",
                "--",
                rel,
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if out.returncode != 0:
            return {"available": False, "error": (out.stderr or "").strip()[:200]}
        versions = []
        for rec in out.stdout.split("\x1e"):
            rec = rec.strip("\n")
            if not rec:
                continue
            parts = rec.split("\x1f")
            if len(parts) < 4:
                continue
            versions.append(
                {
                    "sha": parts[0],
                    "date": parts[1],
                    "author": parts[2],
                    "subject": parts[3],
                }
            )
        return {"available": True, "versions": versions, "count": len(versions)}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "error": str(exc)}


# ── AP AST source: ONE warm instance per viz process ───────────────────
# WorkflowGraphASTSource pins a single event loop on a dedicated thread
# (_SyncLoop) and keeps the AP MCP connection alive across calls. The old
# code spawned a fresh APBridge + asyncio.run() per request, which failed
# to connect from the detached viz subprocess ("connect_failed"). A
# module-level singleton connects once and is reused, and its label-by-
# label queries match AP's LadybugDB schema (a single multi-label MATCH
# is rejected by the engine). source: 2026-05-31 Phase 2 warm-pool.
_AST_SOURCE = None
_AST_SOURCE_LOCK = None


def _get_ast_source():
    global _AST_SOURCE, _AST_SOURCE_LOCK
    if _AST_SOURCE_LOCK is None:
        import threading

        _AST_SOURCE_LOCK = threading.Lock()
    with _AST_SOURCE_LOCK:
        if _AST_SOURCE is None:
            from mcp_server.infrastructure.workflow_graph_source_ast import (
                WorkflowGraphASTSource,
            )

            _AST_SOURCE = WorkflowGraphASTSource()
        return _AST_SOURCE


_AST_CONTEXT_CAP = 20  # source: architect plan — bound get_context fan-out


def _ast_and_impact(path: str) -> dict:
    """AST symbols defined in the file + per-symbol 360° context and the
    blast radius of the first symbol, via the warm AP source. Uses AP's
    typed ``get_context`` (per symbol, capped at N=20) and ``get_impact``
    (once, on the first symbol) instead of hand-written Cypher. Degrades
    gracefully to ``{available: False, reason}`` when AP is off /
    unreachable.

    Returned shape is preserved: ``{available, symbols, impact}``. ``impact``
    is enriched — it carries ``communities_affected`` / ``processes_affected``
    from ``get_impact`` plus the raw affected lists.
    """
    try:
        from mcp_server.infrastructure import ap_bridge
        from mcp_server.infrastructure.ap_bridge import resolve_graph_paths

        if not ap_bridge.is_enabled():
            return {"available": False, "reason": "ap_disabled"}

        src = _get_ast_source()
        # load_symbols([path]) returns rows shaped
        # {file_path, qualified_name, symbol_type, signature, language,
        #  line, domain} — matched by path tail, so abs or repo-relative
        # both work.
        symbols = src.load_symbols([path]) or []
        if not symbols:
            return {"available": True, "symbols": [], "impact": []}

        graph_paths = resolve_graph_paths()
        gp = graph_paths[0] if graph_paths else None
        if not gp:
            return {"available": True, "symbols": symbols, "impact": []}

        loop_run = src._loop_owner.run  # noqa: SLF001
        bridge = src._bridge  # noqa: SLF001

        # Enrich the first up-to-N symbols with AP's typed 360° context.
        # Each call is serialized onto the warm pinned loop — no fresh
        # APBridge, no asyncio.run.
        for sym in symbols[:_AST_CONTEXT_CAP]:
            qn = sym.get("qualified_name")
            if not qn:
                continue
            try:
                ctx = loop_run(bridge.get_context(gp, qn))
            except Exception:
                ctx = None
            if isinstance(ctx, dict):
                sym["context"] = {
                    "relationships": ctx.get("relationships") or {},
                    "community": ctx.get("community") or {},
                    "processes": ctx.get("processes") or [],
                }

        # Blast-radius for the first symbol via the typed get_impact tool.
        impact: dict = {}
        try:
            qn0 = symbols[0].get("qualified_name")
            if qn0:
                impact_raw = loop_run(bridge.get_impact(gp, qn0))
                if isinstance(impact_raw, dict):
                    impact = {
                        "qualified_name": impact_raw.get("qualified_name"),
                        "communities": impact_raw.get("communities") or [],
                        "communities_affected": impact_raw.get("communities_affected"),
                        "processes": impact_raw.get("processes") or [],
                        "processes_affected": impact_raw.get("processes_affected"),
                    }
        except Exception:
            impact = {}

        return {"available": True, "symbols": symbols, "impact": impact}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "error": str(exc)}


def serve_trace_file(handler) -> None:
    """GET /api/trace/file?path=<p> — L3 file drill: AST + impact + git."""
    try:
        path = _param(handler, "path")
        if not path:
            send_json_ok(handler, {"error": "missing path"})
            return
        send_json_ok(
            handler,
            {
                "path": path,
                "git": _git_history(path),
                "versions": _git_versions(path),
                "ast": _ast_and_impact(path),
                "meta": {"schema": "trace.v1", "level": 3},
            },
        )
    except Exception as e:
        send_json_error(handler, e)


def _basename(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/").split("/")[-1]


def _impact_for_graph(graph_path: str, rel_path: str) -> dict | None:
    """Run the exact-path impact queries against ONE code-graph.

    Returns the impact dict (``downstream, upstream, members, processes,
    references, referenced_by, depends_on, depended_on_by`` plus the new
    ``implements``, ``community``, ``communities_affected``,
    ``processes_affected``) or None if the file has no symbols in this
    graph (so the caller can try the next graph).

    Symbol-level direction (calls/imports/callers/implements) is derived
    from AP's typed ``get_context`` tool — one call per member symbol,
    capped at N=20. Files with more than N members fall back to the
    targeted per-file Cypher path (bounds AP fan-out). File→File edges,
    the present-gate, the members list, and the rollup stay on Cypher —
    AP exposes no file-level typed tool for those.
    """
    from mcp_server.infrastructure.workflow_graph_source_ast import _as_list

    # Reuse the warm AST source's pinned loop + persistent AP connection.
    # A fresh APBridge + asyncio.run() per HTTP request collides with the
    # warm bridge on the same AP subprocess (relationship MATCH queries
    # silently returned 0 over HTTP while single-node MATCH worked). The
    # source serializes every call onto one loop, which is reliable.
    src = _get_ast_source()
    loop_run = src._loop_owner.run  # noqa: SLF001
    bridge = src._bridge  # noqa: SLF001

    async def _run() -> dict | None:
        if True:

            async def q(cypher):
                rows = await bridge.query_graph(graph_path, cypher)
                return _as_list(rows)

            # LEGITIMATE query_graph use: present-gate. AP has no typed
            # "is this file in the graph" tool. (cheap gate)
            present = await q(
                "MATCH (f:File) WHERE f.id = '%s' RETURN f.id AS id LIMIT 1"
                % rel_path.replace("'", "")
            )
            if not present:
                return None

            esc = rel_path.replace("'", "")
            # LEGITIMATE query_graph use: members list. This is the N source
            # that drives the typed get_context fan-out below; AP has no
            # file-scoped "list members" typed tool.
            members_rows = await q(
                "MATCH (s:Function) WHERE s.qualified_name STARTS WITH '%s::' "
                "RETURN DISTINCT s.qualified_name AS name LIMIT 200" % esc
            )
            member_qns = [r.get("name") for r in members_rows if r.get("name")]

            def _file_of(qn):
                return str(qn or "").partition("::")[0]

            def _short_name(qn):
                return str(qn or "").split("::")[-1]

            def _conf(r):
                try:
                    return float(r.get("conf")) if r.get("conf") is not None else None
                except (TypeError, ValueError):
                    return None

            downstream: list[dict] = []
            upstream: list[dict] = []
            implements: list[dict] = []
            community: dict = {}

            if member_qns and len(member_qns) <= _AST_CONTEXT_CAP:
                # Typed path: AP's get_context per member (capped at N).
                # downstream = calls + imports + uses; upstream = called_by
                # + imported_by + used_by; plus implements/implemented_by.
                seen_down: set[str] = set()
                seen_up: set[str] = set()
                seen_impl: set[str] = set()

                def _item(rel, kind):
                    qn = rel.get("qualified_name") or rel.get("name")
                    if not qn:
                        return None
                    return {
                        "file": _file_of(qn),
                        "name": qn,
                        "label": _short_name(qn),
                        "kind": kind,
                        "confidence": None,  # get_context items carry no conf
                    }

                for qn in member_qns:
                    try:
                        ctx = await bridge.get_context(graph_path, qn)
                    except Exception:
                        ctx = None
                    if not isinstance(ctx, dict):
                        continue
                    rels = ctx.get("relationships") or {}
                    for rel in rels.get("calls") or []:
                        it = _item(rel, "calls")
                        if it and it["name"] not in seen_down:
                            seen_down.add(it["name"])
                            downstream.append(it)
                    for rel in rels.get("imports") or []:
                        it = _item(rel, "imports")
                        if it and it["name"] not in seen_down:
                            seen_down.add(it["name"])
                            downstream.append(it)
                    for rel in rels.get("uses") or []:
                        it = _item(rel, "uses")
                        if it and it["name"] not in seen_down:
                            seen_down.add(it["name"])
                            downstream.append(it)
                    for rel in rels.get("called_by") or []:
                        it = _item(rel, "calls")
                        if it and it["name"] not in seen_up:
                            seen_up.add(it["name"])
                            upstream.append(it)
                    for rel in rels.get("imported_by") or []:
                        it = _item(rel, "imports")
                        if it and it["name"] not in seen_up:
                            seen_up.add(it["name"])
                            upstream.append(it)
                    for rel in rels.get("used_by") or []:
                        it = _item(rel, "uses")
                        if it and it["name"] not in seen_up:
                            seen_up.add(it["name"])
                            upstream.append(it)
                    for rel in (rels.get("implements") or []) + (
                        rels.get("implemented_by") or []
                    ):
                        it = _item(rel, "implements")
                        if it and it["name"] not in seen_impl:
                            seen_impl.add(it["name"])
                            implements.append(it)
                    if not community and ctx.get("community"):
                        community = ctx.get("community") or {}
            else:
                # FALLBACK path: file has >N members (or none). Avoid firing
                # 200 get_context calls — use the targeted per-file Cypher.
                # LEGITIMATE query_graph use under the N-cap fallback.
                calls = await q(
                    "MATCH (s:Function)-[r:Calls_Function_Function]->(d:Function) "
                    "WHERE s.qualified_name STARTS WITH '%s::' "
                    "RETURN DISTINCT d.qualified_name AS name, r.confidence AS conf "
                    "LIMIT 200" % esc
                )
                imports = await q(
                    "MATCH (f:File)-[r:Imports_File_Function]->(d:Function) "
                    "WHERE f.id = '%s' "
                    "RETURN DISTINCT d.qualified_name AS name, r.confidence AS conf "
                    "LIMIT 200" % esc
                )
                callers = await q(
                    "MATCH (s:Function)-[r:Calls_Function_Function]->(d:Function) "
                    "WHERE d.qualified_name STARTS WITH '%s::' "
                    "RETURN DISTINCT s.qualified_name AS name, r.confidence AS conf "
                    "LIMIT 200" % esc
                )
                for r in calls + imports:
                    nm = r.get("name")
                    if not nm:
                        continue
                    downstream.append(
                        {
                            "file": _file_of(nm),
                            "name": nm,
                            "label": _short_name(nm),
                            "kind": "calls" if r in calls else "imports",
                            "confidence": _conf(r),
                        }
                    )
                upstream = [
                    {
                        "file": _file_of(r.get("name")),
                        "name": r.get("name"),
                        "label": _short_name(r.get("name")),
                        "kind": "calls",
                        "confidence": _conf(r),
                    }
                    for r in callers
                    if r.get("name")
                ]

            # LEGITIMATE query_graph use: File→File edges. AP all-file
            # indexing (>= 0.2.0): Imports_File_File = .js import/require;
            # References_File_File = Markdown/doc links. No typed tool covers
            # these non-AST direct file edges.
            file_imports = await q(
                "MATCH (f:File)-[r:Imports_File_File]->(d:File) "
                "WHERE f.id = '%s' "
                "RETURN DISTINCT d.id AS name, r.confidence AS conf LIMIT 200" % esc
            )
            file_imported_by = await q(
                "MATCH (s:File)-[r:Imports_File_File]->(f:File) "
                "WHERE f.id = '%s' "
                "RETURN DISTINCT s.id AS name, r.confidence AS conf LIMIT 200" % esc
            )
            doc_refs = await q(
                "MATCH (f:File)-[r:References_File_File]->(d:File) "
                "WHERE f.id = '%s' "
                "RETURN DISTINCT d.id AS name, r.confidence AS conf LIMIT 200" % esc
            )
            doc_referenced_by = await q(
                "MATCH (s:File)-[r:References_File_File]->(f:File) "
                "WHERE f.id = '%s' "
                "RETURN DISTINCT s.id AS name, r.confidence AS conf LIMIT 200" % esc
            )

            members = [
                {
                    "file": rel_path,
                    "name": qn,
                    "label": _short_name(qn),
                    "kind": "member",
                    "confidence": None,
                }
                for qn in member_qns
            ]

            # Blast-radius counts via AP's typed get_impact (first member).
            # processes/communities affected are the headline numbers the
            # panel shows; the entry-point process list below stays on Cypher.
            communities_affected = None
            processes_affected = None
            try:
                if member_qns:
                    imp = await bridge.get_impact(graph_path, member_qns[0])
                    if isinstance(imp, dict):
                        communities_affected = imp.get("communities_affected")
                        processes_affected = imp.get("processes_affected")
            except Exception:
                pass

            # LEGITIMATE query_graph use: entry-point processes (causal
            # chains ENTERED from this file). AP's get_processes is graph-wide
            # (not file-scoped); this targeted Cypher filters to this file's
            # entry points. entry_point_id is ``file::symbol``.
            processes_rows = await q(
                "MATCH (p:Process) WHERE p.entry_point_id STARTS WITH '%s::' "
                "RETURN DISTINCT p.entry_point_id AS entry, p.entry_kind AS kind, "
                "p.depth AS depth, p.symbol_count AS n "
                "ORDER BY p.symbol_count DESC LIMIT 40" % esc
            )
            processes = []
            for r in processes_rows:
                entry = r.get("entry")
                if not entry:
                    continue
                processes.append(
                    {
                        "entry": entry,
                        "label": _short_name(entry),
                        "kind": r.get("kind"),
                        "depth": r.get("depth"),
                        "symbol_count": r.get("n"),
                    }
                )

            # ── File-level rollup: the "what does changing this break" view.
            # Collapse symbol edges to distinct FILES, with edge counts, so a
            # developer sees file→file blast radius at a glance (direction:
            # depends_on = downstream files, depended_on_by = upstream files).
            def _rollup(items):
                agg: dict[str, dict] = {}
                for it in items:
                    fp = it.get("file")
                    if not fp or fp == rel_path:
                        continue
                    e = agg.setdefault(
                        fp,
                        {
                            "file": fp,
                            "label": _basename(fp),
                            "edges": 0,
                            "kinds": set(),
                        },
                    )
                    e["edges"] += 1
                    if it.get("kind"):
                        e["kinds"].add(it["kind"])
                out = []
                for e in agg.values():
                    e["kinds"] = sorted(e["kinds"])
                    out.append(e)
                out.sort(key=lambda x: x["edges"], reverse=True)
                return out

            def _file_edges(rows, kind):
                out = []
                for r in rows:
                    nm = r.get("name")
                    if not nm or nm == rel_path:
                        continue
                    out.append(
                        {
                            "file": nm,
                            "label": _basename(nm),
                            "kind": kind,
                            "confidence": _conf(r),
                        }
                    )
                return out

            # Direct File→File edges (AP all-file indexing): code imports for
            # non-AST files (.js) and doc references (Markdown). Folded into the
            # file-level direction so the panel shows them even when a file has
            # no AST symbols at all.
            imports_files = _file_edges(file_imports, "imports")
            imported_by_files = _file_edges(file_imported_by, "imports")
            references = _file_edges(doc_refs, "references")
            referenced_by = _file_edges(doc_referenced_by, "references")

            return {
                "downstream": downstream,
                "upstream": upstream,
                "members": members,
                "processes": processes,
                "references": references,
                "referenced_by": referenced_by,
                "depends_on": _rollup(downstream + imports_files),
                "depended_on_by": _rollup(upstream + imported_by_files),
                # New AP-typed enrichment fields (additive — frontend may
                # ignore them without breaking the existing direction view).
                "implements": implements,
                "community": community,
                "communities_affected": communities_affected,
                "processes_affected": processes_affected,
            }

    return loop_run(_run())


def _to_repo_relative(path: str) -> str:
    """Normalize a file path to the project-root-relative form AP indexes.

    AP's ``File.id`` is repo-relative (``mcp_server/server/http_standalone.py``).
    Graph file nodes carry the absolute tool-call path, so callers pass an
    absolute path; make it relative to its git root so the exact ``f.id =``
    match in ``_impact_for_graph`` lands. A relative path is just cleaned;
    if no git root resolves, fall back to stripping the leading slash.
    """
    p = (path or "").replace("\\", "/")
    if not p.startswith("/"):
        # Relative input — reject ``..`` traversal, return cleaned.
        if ".." in [seg for seg in p.split("/")]:
            return ""
        return p.lstrip("./")
    from pathlib import Path

    from mcp_server.infrastructure.git_diff import find_git_root
    from mcp_server.server.http_file_diff import _contained_resolved

    # Sanitise-and-return (CWE-22): ``ap`` is None unless ``p`` resolves
    # inside an allowed root (HOME / cwd / temp). ``is_relative_to`` is the
    # canonical path-traversal barrier, applied inline before ``ap`` reaches
    # any filesystem op — a crafted ``?path=`` cannot reach ``/etc`` /
    # ``/root``. ``?path=`` is loopback-only and normally carries the user's
    # own file node path; this just bounds the surface.
    ap = _contained_resolved(p)
    if ap is None:
        return p.lstrip("/")
    try:
        root = find_git_root(ap.parent)
        if root is not None:
            return str(ap.relative_to(Path(root).resolve(strict=False)))
    except (OSError, ValueError):
        pass
    return p.lstrip("/")


def serve_trace_impact(handler) -> None:
    """GET /api/trace/impact?path=<file> — dependency/impact subgraph.

    Blast-radius for a file from the AP code-graph:
      * downstream — what this file calls / imports (it depends on these)
      * upstream   — what calls this file (these break if it changes)
      * members    — symbols this file defines
    Queries the FIRST code-graph that contains the file (exact File.id
    match), so it hits the Cortex graph for a Cortex path rather than
    scanning all 6 graphs. ``{available: False, reason}`` when off / not
    indexed.
    """
    try:
        from mcp_server.infrastructure import ap_bridge

        path = _param(handler, "path")
        if not path:
            send_json_ok(handler, {"available": False, "reason": "missing path"})
            return
        if not ap_bridge.is_enabled():
            send_json_ok(handler, {"available": False, "reason": "ap_disabled"})
            return

        # AP indexes File.id project-root-RELATIVE (e.g.
        # "mcp_server/server/http_standalone.py"). File nodes in the graph
        # carry the ABSOLUTE tool-call path, so the frontend sends an
        # absolute path here; the old ``lstrip("./")`` turned
        # "/Users/.../mcp_server/x.py" into "Users/.../mcp_server/x.py",
        # matching no File.id → every diagram returned "not_indexed". Strip
        # the git root so the exact ``f.id =`` match lands.
        rel = _to_repo_relative(path)
        # Several graphs may contain the same relative path (a stale legacy
        # index AND the fresh Cortex code-graph). The first hit can be the
        # stale one with members-only and no edges, so pick the RICHEST
        # result (most call/import edges) across all graphs that have it.
        result = None
        best_edges = -1
        for gp in ap_bridge.resolve_graph_paths():
            try:
                r = _impact_for_graph(gp, rel)
            except Exception:
                r = None
            if r is None:
                continue
            n = (
                len(r.get("downstream", []))
                + len(r.get("upstream", []))
                + len(r.get("members", []))
                + len(r.get("processes", []))
                + len(r.get("references", []))
                + len(r.get("referenced_by", []))
                + len(r.get("depends_on", []))
                + len(r.get("depended_on_by", []))
            )
            if n > best_edges:
                best_edges = n
                result = r

        if result is None:
            send_json_ok(
                handler,
                {
                    "available": False,
                    "reason": "not_indexed",
                    "path": path,
                    "center": {"file": path, "label": _basename(path)},
                },
            )
            return

        result.update(
            {
                "available": True,
                "path": path,
                "center": {"file": path, "label": _basename(path)},
                "versions": _git_versions(path),
                "meta": {"schema": "trace.v1", "level": 4},
            }
        )
        send_json_ok(handler, result)
    except Exception as e:
        send_json_error(handler, e)


__all__ = [
    "serve_trace_domains",
    "serve_trace_sessions",
    "serve_trace_chain",
    "serve_trace_file",
    "serve_trace_impact",
]
