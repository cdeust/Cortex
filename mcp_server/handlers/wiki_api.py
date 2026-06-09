"""Wiki API handlers for the visualization HTTP server.

Filesystem-backed endpoints (unchanged since Phase 1):
  /api/wiki/list   — enumerate .md files
  /api/wiki/page   — read one .md file

DB-backed endpoints (Phase 6 — expose the redesigned layers):
  /api/wiki/page_meta  — thermo state + citations + backlinks for one page
  /api/wiki/concepts   — list candidate/saturating/promoted concepts
  /api/wiki/drafts     — list drafts, filter by status/kind
  /api/wiki/memos      — audit trail for a subject (page/draft/concept/claim)
  /api/wiki/views      — list available views
  /api/wiki/view       — execute a view by name

All DB endpoints gracefully return empty results if the wiki.* schema
isn't populated yet. Never raises — errors become {"error": "..."}.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from mcp_server.core.wiki_pages import parse_page
from mcp_server.core.wiki_view_executor import compile_view
from mcp_server.infrastructure.wiki_store import list_pages, read_page


def list_wiki_pages(wiki_root: Path) -> list[dict]:
    """List all wiki pages with parsed frontmatter metadata."""
    pages = list_pages(wiki_root)
    result = []
    for rel_path in pages:
        content = read_page(wiki_root, rel_path)
        if content is None:
            continue
        doc = parse_page(content)
        fm = doc.frontmatter
        stem = Path(rel_path).stem
        result.append(
            {
                "path": rel_path,
                "title": fm.get("title", stem),
                "kind": fm.get("kind", ""),
                "domain": fm.get("domain", ""),
                "maturity": fm.get("maturity", ""),
                "tags": fm.get("tags", []),
                "created": str(fm.get("created", "")),
                "updated": str(fm.get("updated", "")),
            }
        )
    return result


def read_wiki_page(wiki_root: Path, rel_path: str) -> dict:
    """Read a single wiki page with metadata and body."""
    if "/../" in rel_path or rel_path.startswith("../") or "\x00" in rel_path:
        return {"error": "invalid path"}
    content = read_page(wiki_root, rel_path)
    if content is None:
        return {"error": "not found", "path": rel_path}
    doc = parse_page(content)
    return {
        "path": rel_path,
        "meta": doc.frontmatter,
        "body": doc.body,
    }


# ── DB-backed endpoints (Phase 6) ─────────────────────────────────────


def _get_store():
    """Lazy store accessor — never raises; returns None if DB missing."""
    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        settings = get_memory_settings()
        return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    except Exception:
        return None


def _rows_to_plain(rows: list[Any]) -> list[dict]:
    """Coerce psycopg rows to plain JSON-serialisable dicts."""
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            clean = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    clean[k] = v.hex()
                else:
                    clean[k] = v
            out.append(clean)
    return out


def page_meta(rel_path: str) -> dict:
    """Return thermodynamic state + links + recent citations for one page.

    Input is the same rel_path used by read_wiki_page. DB lookup by
    rel_path joins against wiki.links and wiki.citations.
    """
    if not rel_path or "/../" in rel_path or rel_path.startswith("../"):
        return {"error": "invalid path"}
    store = _get_store()
    if store is None:
        return {"error": "db unavailable"}
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, title, kind, domain, status, lifecycle_state,
                   heat, access_count, citation_count, backlink_count,
                   is_stale, planted, tended, last_cited_at, archived_at,
                   memory_id, concept_id
              FROM wiki.pages
             WHERE rel_path = %s
             LIMIT 1
            """,
            (rel_path,),
        )
        page = cur.fetchone()
    if page is None:
        return {"rel_path": rel_path, "db_row": None}

    page_id = page["id"]
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT src_page_id, dst_slug, dst_page_id, link_kind,
                   (SELECT title FROM wiki.pages WHERE id = l.src_page_id) AS src_title,
                   (SELECT rel_path FROM wiki.pages WHERE id = l.src_page_id) AS src_rel_path
              FROM wiki.links l
             WHERE dst_page_id = %s
             LIMIT 100
            """,
            (page_id,),
        )
        backlinks = _rows_to_plain(list(cur.fetchall()))
        cur.execute(
            """
            SELECT dst_slug, dst_page_id, link_kind
              FROM wiki.links WHERE src_page_id = %s LIMIT 100
            """,
            (page_id,),
        )
        out_links = _rows_to_plain(list(cur.fetchall()))
        cur.execute(
            """
            SELECT id, session_id, domain, memory_id, cited_at
              FROM wiki.citations
             WHERE page_id = %s ORDER BY cited_at DESC LIMIT 20
            """,
            (page_id,),
        )
        citations = _rows_to_plain(list(cur.fetchall()))

    return {
        "rel_path": rel_path,
        "db_row": _rows_to_plain([page])[0],
        "backlinks": backlinks,
        "outbound_links": out_links,
        "recent_citations": citations,
    }


def list_concepts(status: str | None = None, limit: int = 100) -> dict:
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "concepts": []}
    sql = (
        "SELECT id, label, status, saturation_streak, "
        "array_length(entity_ids, 1) AS n_entities, "
        "array_length(grounding_memory_ids, 1) AS n_memories, "
        "array_length(grounding_claim_ids, 1) AS n_claims, "
        "promoted_page_id "
        "FROM wiki.concepts"
    )
    params: list = []
    if status:
        sql += " WHERE status = %s"
        params.append(status)
    sql += " ORDER BY saturation_streak DESC NULLS LAST, id DESC LIMIT %s"
    params.append(limit)
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"concepts": rows, "count": len(rows)}


def list_drafts(
    status: str | None = None, kind: str | None = None, limit: int = 100
) -> dict:
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "drafts": []}
    where: list[str] = []
    params: list = []
    if status:
        where.append("status = %s")
        params.append(status)
    if kind:
        where.append("kind = %s")
        params.append(kind)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, concept_id, memory_id, kind, title, status, "
        "confidence, synth_model, created_at, reviewed_at, published_page_id "
        f"FROM wiki.drafts{where_sql} "
        "ORDER BY created_at DESC LIMIT %s"
    )
    params.append(limit)
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"drafts": rows, "count": len(rows)}


def list_memos(subject_type: str, subject_id: int, limit: int = 50) -> dict:
    if subject_type not in ("page", "concept", "draft", "claim"):
        return {"error": f"invalid subject_type: {subject_type!r}", "memos": []}
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "memos": []}
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, decision, rationale, confidence, author, created_at,
                   inputs
              FROM wiki.memos
             WHERE subject_type = %s AND subject_id = %s
             ORDER BY created_at DESC LIMIT %s
            """,
            (subject_type, subject_id, limit),
        )
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"memos": rows, "count": len(rows)}


def list_views() -> dict:
    """Views live in wiki/_views/*.md; loader handles them."""
    try:
        from mcp_server.core.wiki_schema_loader import load_registry
        from mcp_server.infrastructure.config import WIKI_ROOT

        registry = load_registry(Path(WIKI_ROOT))
    except Exception as e:
        return {"error": str(e), "views": []}
    return {
        "views": [
            {
                "name": v.name,
                "rel_path": v.rel_path,
                "description": v.description,
            }
            for v in registry.views.values()
        ],
        "count": len(registry.views),
    }


def execute_view(name: str | None, inline_query: str | None = None) -> dict:
    """Execute a named view or an inline cortex-query block."""
    try:
        from mcp_server.core.wiki_schema_loader import load_registry
        from mcp_server.infrastructure.config import WIKI_ROOT
    except Exception as e:
        return {"error": f"config error: {e}"}

    if name:
        try:
            registry = load_registry(Path(WIKI_ROOT))
        except Exception as e:
            return {"error": f"registry load failed: {e}"}
        view = registry.views.get(name)
        if view is None:
            return {
                "error": f"view {name!r} not found",
                "available": list(registry.views.keys()),
            }
        query_text = view.query
        view_meta = {"name": view.name, "rel_path": view.rel_path}
    elif inline_query:
        query_text = inline_query
        view_meta = {"name": "<inline>", "rel_path": None}
    else:
        return {"error": "name or query is required"}

    compiled = compile_view(query_text)
    if not compiled.ok:
        return {
            "view": view_meta,
            "error": "compile failed",
            "errors": compiled.errors,
        }

    store = _get_store()
    if store is None:
        return {"view": view_meta, "error": "db unavailable"}
    with store._conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(compiled.sql, compiled.params)
            rows = _rows_to_plain(list(cur.fetchall()))
        except Exception as e:
            return {"view": view_meta, "error": f"execution failed: {e}"}

    return {
        "view": view_meta,
        "table": compiled.table,
        "row_count": len(rows),
        "rows": rows,
    }


def list_bibliography(wiki_root: Path) -> dict:
    """List `.bib` files under wiki/_bibliography/ (Phase 9.1).

    Scientists drop BibTeX files there; the frontend fetches them and
    Citation.js parses them into a key → entry lookup for cite-key
    resolution (`[@author2024]` → formatted citation).

    Returns {"files": [{"path": "...", "size": N, "entries": int}]}.
    """
    bib_dir = wiki_root / "_bibliography"
    if not bib_dir.exists() or not bib_dir.is_dir():
        return {"files": []}
    out = []
    try:
        for p in sorted(bib_dir.rglob("*.bib")):
            try:
                rel = str(p.relative_to(wiki_root)).replace("\\", "/")
                # Cheap entry count: every BibTeX record starts with `@`
                content = p.read_text(encoding="utf-8", errors="replace")
                entries = content.count("\n@") + (1 if content.startswith("@") else 0)
                out.append(
                    {
                        "path": rel,
                        "size": p.stat().st_size,
                        "entries": entries,
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return {"files": out}


def read_bibliography(wiki_root: Path, rel_path: str) -> dict:
    """Return raw BibTeX content for one file.

    Path validation via the existing CodeQL-verified wiki_store
    commonpath sanitizer — we only serve files whose rel_path resolves
    inside wiki_root. Must live under _bibliography/ to prevent
    arbitrary file reads under the cover of this endpoint.
    """
    if not rel_path or "/../" in rel_path or rel_path.startswith("../"):
        return {"error": "invalid path"}
    if not rel_path.startswith("_bibliography/") or not rel_path.endswith(".bib"):
        return {"error": "must be a .bib file under _bibliography/"}
    content = read_page(wiki_root, rel_path)
    if content is None:
        return {"error": "not found", "path": rel_path}
    return {"path": rel_path, "content": content, "size": len(content)}


# ── Cross-lens documentation graph (workflow_graph.v1) ────────────────


def _scope_of(rel_path: str) -> str:
    """Map a page rel_path to its structural scope name (cluster key).

    Pre: rel_path is wiki-relative (``<dir>/<domain>/<slug>.md`` or
    ``<dir>/<slug>.md``).
    Post: returns the first Scope whose ``directories`` contains the
    leading path segment; ``"_other"`` when none matches. Pure — same
    matching logic serve_wiki_projects uses for path → scope.
    """
    from mcp_server.core.wiki_coverage import SCOPES

    head = rel_path.split("/", 1)[0] if rel_path else ""
    for scope in SCOPES:
        if head in scope.directories:
            return scope.name
    return "_other"


# Inline ``[[target]]`` wikilink. Pages overwhelmingly carry links this way
# (167/443 pages on the live wiki vs 7 using classic ``[text](url)`` Related
# blocks), including inside ``## Related`` sections, so a single body-wide
# scan over the markdown captures both surfaces. source: measured on
# 2026-06-02 against ~/.claude/methodology/wiki.
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _resolve_wikilink(target: str, known: set[str], stem_index: dict[str, str]) -> str:
    """Resolve a ``[[target]]`` payload to an in-graph page rel_path or ``""``.

    Pre: ``known`` is the set of page-node rel_paths in this graph;
    ``stem_index`` maps each page's filename stem → its rel_path.
    Post: returns the rel_path of the page the link points at, but ONLY
    when it is one of the graph's page nodes; ``""`` otherwise. Resolution
    order (most → least specific): exact rel_path, ``<target>.md`` (the
    ``[[reference/<domain>/<slug>]]`` convention → ``…/<slug>.md``), then
    bare-stem match. Pure — no I/O, no mutation.
    """
    t = target.strip()
    if not t:
        return ""
    # Drop any ``#anchor`` / ``|alias`` suffixes a wikilink may carry.
    t = t.split("#", 1)[0].split("|", 1)[0].strip()
    if not t:
        return ""
    if t in known:
        return t
    candidate = t if t.endswith(".md") else t + ".md"
    if candidate in known:
        return candidate
    stem = Path(t).stem
    hit = stem_index.get(stem)
    return hit or ""


def _body_wiki_link_edges(
    read_body,
    page_nodes: list[dict],
    existing: set[tuple[str, str]],
) -> list[dict]:
    """Derive ``wiki_link`` edges from page bodies (``[[wikilink]]`` scan).

    Pre: ``read_body(rel_path) -> str | None`` returns a page's markdown
    (filesystem-backed); ``page_nodes`` are the graph's ``wiki_page`` nodes;
    ``existing`` holds already-emitted ``(source, target)`` pairs to dedupe
    against (e.g. PG-derived links). Post: returns new ``wiki_link`` edges
    {source, target, kind, link_kind: "related"} for every body link that
    resolves to another page node and is not already present. Self-links are
    skipped. Bounded by the already-capped ``page_nodes`` set; unreadable
    pages are skipped silently.
    """
    rels = [n["id"] for n in page_nodes]
    known = set(rels)
    stem_index: dict[str, str] = {}
    for rel in rels:
        # First writer wins → deterministic for duplicate stems across dirs.
        stem_index.setdefault(Path(rel).stem, rel)
    out: list[dict] = []
    for rel in rels:
        try:
            body = read_body(rel)
        except Exception:
            body = None
        if not body:
            continue
        for raw in _WIKILINK_RE.findall(body):
            dst = _resolve_wikilink(raw, known, stem_index)
            if not dst or dst == rel:
                continue
            pair = (rel, dst)
            if pair in existing:
                continue
            existing.add(pair)
            out.append(
                {
                    "source": rel,
                    "target": dst,
                    "kind": "wiki_link",
                    "link_kind": "related",
                }
            )
    return out


def _wiki_graph_db(store, domain: str, cooccur: bool, xlens: bool) -> dict:
    """Build the cross-lens graph from PG ``wiki.*`` for one domain.

    Pre: store is a live MemoryStore; domain is a non-empty project id.
    Post: returns a workflow_graph.v1 dict (nodes/edges/meta). Cheap core
    (pages, wiki_link, provenance) ALWAYS runs; cooccur / xlens run only
    when toggled and are bounded by hard caps. Returns {} when the
    ``wiki.pages`` table is empty for the domain so the caller can fall
    back to the filesystem.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    page_by_id: dict[int, dict] = {}  # wiki.pages.id -> row

    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, rel_path, title, domain, kind, tags, heat,
                   memory_id, concept_id
              FROM wiki.pages
             WHERE domain = %s
             ORDER BY id
             LIMIT 2000
            """,
            (domain,),
        )
        pages = list(cur.fetchall())

    if not pages:
        return {}

    # ── Domain hub node so the renderer's domainOf resolves every page ──
    domain_node_id = "domain:" + domain
    nodes.append(
        {"id": domain_node_id, "kind": "domain", "label": domain, "domain": domain}
    )

    # ── Cheap core ALWAYS: pages → wiki_page nodes (scope cluster) ──
    page_ids: list[int] = []
    for p in pages:
        page_by_id[p["id"]] = p
        page_ids.append(p["id"])
        scope = _scope_of(p["rel_path"] or "")
        nodes.append(
            {
                "id": p["rel_path"],
                "kind": "wiki_page",
                "label": p["title"] or Path(p["rel_path"]).stem,
                "cluster": scope,
                "domain": domain_node_id,
                "heat": p.get("heat") or 0.0,
            }
        )

    # ── Cheap core ALWAYS: wiki.links → wiki_link edges ──
    # Track (src, dst) rel_path pairs so body-derived links (below) dedupe
    # against the PG path and we never double-add the same edge.
    wiki_link_pairs: set[tuple[str, str]] = set()
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT src_page_id, dst_page_id, link_kind
              FROM wiki.links
             WHERE src_page_id = ANY(%s) AND dst_page_id = ANY(%s)
             LIMIT 5000
            """,
            (page_ids, page_ids),
        )
        for ln in cur.fetchall():
            src = page_by_id.get(ln["src_page_id"])
            dst = page_by_id.get(ln["dst_page_id"])
            if not src or not dst:
                continue
            pair = (src["rel_path"], dst["rel_path"])
            if pair in wiki_link_pairs:
                continue
            wiki_link_pairs.add(pair)
            edges.append(
                {
                    "source": src["rel_path"],
                    "target": dst["rel_path"],
                    "kind": "wiki_link",
                    "link_kind": ln["link_kind"],
                }
            )

    # ── Cheap core ALWAYS: body-derived wiki_link edges ──
    # The live ``wiki.links`` table is sparse/empty; the real links live in
    # page bodies as ``[[wikilinks]]`` (including ``## Related`` blocks).
    # Parse the bodies of THIS graph's page set and resolve targets against
    # the same page-node set, deduped against the PG-derived pairs above.
    from mcp_server.infrastructure.config import WIKI_ROOT

    page_nodes = [n for n in nodes if n.get("kind") == "wiki_page"]
    edges.extend(
        _body_wiki_link_edges(
            lambda rel: read_page(WIKI_ROOT, rel),
            page_nodes,
            wiki_link_pairs,
        )
    )

    # ── Cheap core ALWAYS: provenance page → PRD (source: frontmatter
    #    surfaces as a specs/ page) and page → memory (memory_id). ──
    for p in pages:
        rel = p["rel_path"] or ""
        if _scope_of(rel) == "prd":
            prd_id = "prd:" + rel
            nodes.append(
                {
                    "id": prd_id,
                    "kind": "prd",
                    "label": Path(rel).stem,
                    "cluster": "_xlens",
                    "domain": domain_node_id,
                }
            )
            edges.append({"source": rel, "target": prd_id, "kind": "provenance_prd"})
        if p.get("memory_id"):
            mem_id = "memory:" + str(p["memory_id"])
            nodes.append(
                {
                    "id": mem_id,
                    "kind": "memory",
                    "label": "mem " + str(p["memory_id"]),
                    "cluster": "_xlens",
                    "domain": domain_node_id,
                }
            )
            edges.append({"source": rel, "target": mem_id, "kind": "provenance_memory"})

    if xlens:
        _xlens_augment(store, domain_node_id, pages, page_by_id, nodes, edges)
    if cooccur:
        _cooccur_augment(store, pages, page_by_id, edges)

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "schema": "workflow_graph.v1",
            "lens": "wiki",
            "domain": domain,
            "toggles": {"cooccur": cooccur, "xlens": xlens},
        },
    }


def _xlens_augment(store, domain_node_id, pages, page_by_id, nodes, edges) -> None:
    """Cross-lens entity join + deterministic codebase-page → symbol derivation.

    Entity path (reliable): page.memory_id → memory_entities → entities.
    Symbol path (experimental, derived): ``ingest_codebase`` writes one page
    per AP process at ``reference/codebase/<slug>.md`` where ``<slug>`` is the
    slugified process entry_point (see ingest_codebase_pages.render_process_page).
    The slug DETERMINISTICALLY encodes the documented process, so emit a
    derived ``symbol:<slug>`` node + ``xlens_symbol`` edge from the slug alone
    — no AP round-trip, no noisy name-matching. Bounded by page count
    (≤ 2000) and a per-page entity cap.
    """
    mem_to_page: dict[int, str] = {
        p["memory_id"]: p["rel_path"] for p in pages if p.get("memory_id")
    }
    seen_entity_nodes: set[str] = set()
    if mem_to_page:
        with store._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT me.memory_id AS memory_id, e.id AS entity_id, e.name AS name
                  FROM memory_entities me
                  JOIN entities e ON e.id = me.entity_id
                 WHERE me.memory_id = ANY(%s)
                 LIMIT 4000
                """,
                (list(mem_to_page.keys()),),
            )
            for row in cur.fetchall():
                rel = mem_to_page.get(row["memory_id"])
                if not rel:
                    continue
                ent_id = "entity:" + str(row["entity_id"])
                if ent_id not in seen_entity_nodes:
                    seen_entity_nodes.add(ent_id)
                    nodes.append(
                        {
                            "id": ent_id,
                            "kind": "entity",
                            "label": row["name"],
                            "cluster": "_xlens",
                            "domain": domain_node_id,
                        }
                    )
                edges.append({"source": rel, "target": ent_id, "kind": "xlens_entity"})

    # Deterministic reference/codebase/ → AP process/symbol derivation
    # (experimental). ingest_codebase writes these pages; the slug is the
    # slugified process entry_point, so the symbol node is keyed on it.
    _CODEBASE_PREFIX = "reference/codebase/"
    for p in pages:
        rel = p["rel_path"] or ""
        if not rel.startswith(_CODEBASE_PREFIX) or not rel.endswith(".md"):
            continue
        slug = rel[len(_CODEBASE_PREFIX) : -len(".md")]
        sym_id = "symbol:" + slug
        nodes.append(
            {
                "id": sym_id,
                "kind": "symbol",
                "label": slug,
                "cluster": "_xlens",
                "domain": domain_node_id,
                "experimental": True,
            }
        )
        edges.append(
            {
                "source": rel,
                "target": sym_id,
                "kind": "xlens_symbol",
                "experimental": True,
            }
        )


def _cooccur_augment(store, pages, page_by_id, edges) -> None:
    """Concept co-occurrence: pages sharing ≥2 entity_ids/tags (capped).

    EXPENSIVE pairwise — only runs behind the cooccur toggle. Bounded by
    a hard top-N edge cap and a minimum shared-key threshold of 2.
    """
    _MIN_SHARED = 2  # source: plan constraint — min shared keys ≥ 2
    _TOP_N = 300  # hard cap on emitted co-occurrence edges

    # Build a per-page key set from tags (JSONB) + concept entity_ids.
    concept_ids = [p["concept_id"] for p in pages if p.get("concept_id")]
    entity_by_concept: dict[int, set[int]] = {}
    if concept_ids:
        with store._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, entity_ids FROM wiki.concepts WHERE id = ANY(%s)",
                (concept_ids,),
            )
            for row in cur.fetchall():
                entity_by_concept[row["id"]] = set(row.get("entity_ids") or [])

    keys_by_page: dict[str, set] = {}
    for p in pages:
        rel = p["rel_path"]
        keys: set = set()
        tags = p.get("tags")
        if isinstance(tags, list):
            keys.update("tag:" + str(t) for t in tags)
        cid = p.get("concept_id")
        if cid and cid in entity_by_concept:
            keys.update("ent:" + str(e) for e in entity_by_concept[cid])
        if keys:
            keys_by_page[rel] = keys

    rels = list(keys_by_page.keys())
    emitted = 0
    for i in range(len(rels)):
        if emitted >= _TOP_N:
            break
        for j in range(i + 1, len(rels)):
            if emitted >= _TOP_N:
                break
            shared = keys_by_page[rels[i]] & keys_by_page[rels[j]]
            if len(shared) >= _MIN_SHARED:
                edges.append(
                    {
                        "source": rels[i],
                        "target": rels[j],
                        "kind": "concept_cooccur",
                        "weight": len(shared),
                    }
                )
                emitted += 1


def _wiki_graph_fs(wiki_root: Path, domain: str, cooccur: bool, xlens: bool) -> dict:
    """Filesystem fallback: pages + ``## Related`` links when PG is empty.

    Pre: wiki_root exists. Post: workflow_graph.v1 dict with wiki_page
    nodes (scope cluster) and wiki_link edges parsed from each page's
    ``## Related`` block. Provenance/xlens/cooccur are PG-only and absent
    here; meta records the lens so the renderer treats it as a tree.
    """
    from mcp_server.core.wiki_links import _split_body_and_related

    pages = list_wiki_pages(wiki_root)
    domain_node_id = "domain:" + domain
    nodes: list[dict] = [
        {"id": domain_node_id, "kind": "domain", "label": domain, "domain": domain}
    ]
    edges: list[dict] = []
    known: set[str] = set()
    for p in pages:
        rel = p.get("path") or ""
        parts = rel.split("/")
        page_domain = parts[1] if len(parts) >= 3 else "_general"
        if domain and page_domain != domain:
            continue
        known.add(rel)
        nodes.append(
            {
                "id": rel,
                "kind": "wiki_page",
                "label": p.get("title") or Path(rel).stem,
                "cluster": _scope_of(rel),
                "domain": domain_node_id,
                "heat": 0.0,
            }
        )
    # Classic ``- relation → [target](target)`` Related entries first…
    wiki_link_pairs: set[tuple[str, str]] = set()
    page_nodes = [x for x in nodes if x["kind"] == "wiki_page"]
    for n in page_nodes:
        content = read_page(wiki_root, n["id"])
        if content is None:
            continue
        _, entries = _split_body_and_related(content)
        for entry in entries:
            if entry.target not in known:
                continue
            pair = (n["id"], entry.target)
            if pair in wiki_link_pairs:
                continue
            wiki_link_pairs.add(pair)
            edges.append(
                {
                    "source": n["id"],
                    "target": entry.target,
                    "kind": "wiki_link",
                    "link_kind": entry.relation,
                }
            )
    # …then body-wide ``[[wikilink]]`` scan (the dominant link surface here),
    # deduped against the classic entries above.
    edges.extend(
        _body_wiki_link_edges(
            lambda rel: read_page(wiki_root, rel),
            page_nodes,
            wiki_link_pairs,
        )
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "schema": "workflow_graph.v1",
            "lens": "wiki",
            "domain": domain,
            "toggles": {"cooccur": cooccur, "xlens": xlens},
            "source": "fs",
        },
    }


def wiki_graph(domain: str, *, cooccur: bool = False, xlens: bool = False) -> dict:
    """Cross-lens documentation graph for one domain (workflow_graph.v1).

    Pre: domain is a project id. Post: returns {nodes, edges, meta}.
    Reads PG ``wiki.*`` via the shared store; degrades to filesystem
    ``## Related`` frontmatter when the store is unavailable OR the
    ``wiki.pages`` table is empty for the domain. Read-only — never
    mutates. Expensive cooccur / xlens paths run only when toggled.
    """
    from mcp_server.infrastructure.config import METHODOLOGY_DIR

    wiki_root = METHODOLOGY_DIR / "wiki"
    if not domain:
        return {
            "error": "domain required",
            "nodes": [],
            "edges": [],
            "meta": {"schema": "workflow_graph.v1", "lens": "wiki"},
        }
    # UNION the two page sources (deduped by rel_path), not either/or: PG holds
    # memory-synced pages (ADR/spec/note + provenance/entities), while the
    # curated reference/guide pages with [[wikilinks]] live on disk only. A
    # domain with any PG pages used to hide its entire FS-only curated graph.
    # PG nodes/edges take precedence; FS adds the pages PG never synced.
    db_graph: dict = {}
    store = _get_store()
    if store is not None:
        try:
            db_graph = _wiki_graph_db(store, domain, cooccur, xlens) or {}
        except Exception:
            db_graph = {}
    fs_graph: dict = {}
    try:
        fs_graph = _wiki_graph_fs(wiki_root, domain, cooccur, xlens) or {}
    except Exception:
        fs_graph = {}
    return _merge_wiki_graphs(db_graph, fs_graph, domain, cooccur, xlens)


def _merge_wiki_graphs(
    db_graph: dict, fs_graph: dict, domain: str, cooccur: bool, xlens: bool
) -> dict:
    """Union two workflow_graph.v1 payloads. Nodes dedup by id (DB wins on
    metadata — richer: memory_id/heat); edges dedup by (source, target, kind).
    Either input may be empty."""
    nodes: list[dict] = []
    seen_nodes: set[str] = set()
    # DB first so its richer node wins on id collision.
    for g in (db_graph, fs_graph):
        for n in g.get("nodes", []):
            nid = n.get("id")
            if nid is None or nid in seen_nodes:
                continue
            seen_nodes.add(nid)
            nodes.append(n)
    edges: list[dict] = []
    seen_edges: set[tuple] = set()
    for g in (db_graph, fs_graph):
        for e in g.get("edges", []):
            key = (e.get("source"), e.get("target"), e.get("kind"))
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(e)
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "schema": "workflow_graph.v1",
            "lens": "wiki",
            "domain": domain,
            "toggles": {"cooccur": cooccur, "xlens": xlens},
            "sources": {
                "db_pages": sum(
                    1 for n in db_graph.get("nodes", []) if n.get("kind") == "wiki_page"
                ),
                "fs_pages": sum(
                    1 for n in fs_graph.get("nodes", []) if n.get("kind") == "wiki_page"
                ),
            },
        },
    }


def save_wiki_page(wiki_root: Path, rel_path: str, body: str) -> dict:
    """Write ``body`` to ``<wiki_root>/<rel_path>`` atomically.

    Used by the in-browser editor (Phase 8.4). Path validation is
    performed by infrastructure/wiki_store.write_page (commonpath
    sanitizer — CodeQL-verified Phase 6 refactor).

    Returns {"ok": True, "rel_path": ..., "bytes": N} on success,
    or {"error": ...} on failure. Never raises.
    """
    if not rel_path or not isinstance(rel_path, str):
        return {"error": "rel_path required"}
    if body is None:
        return {"error": "body required"}
    if len(body) > 2_000_000:
        return {"error": "body too large (> 2 MB)"}
    try:
        from mcp_server.infrastructure.wiki_store import write_page

        result = write_page(wiki_root, rel_path, body, mode="replace")
        return {
            "ok": True,
            "rel_path": result.path,
            "bytes_written": result.bytes_written,
            "mode": result.mode,
        }
    except Exception as e:
        return {"error": str(e)}


__all__ = [
    "list_wiki_pages",
    "read_wiki_page",
    "save_wiki_page",
    "list_bibliography",
    "read_bibliography",
    "page_meta",
    "list_concepts",
    "list_drafts",
    "list_memos",
    "list_views",
    "execute_view",
    "wiki_graph",
]
