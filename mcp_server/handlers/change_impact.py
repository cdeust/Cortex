"""Handler: change_impact — find memories touched by a commit's code
changes (ADR-0046 Phase 4).

Flow:
  1. Ask AP's ``detect_changes`` for changed symbols and files between
     two commits (defaults: ``HEAD~1``..``HEAD``).
  2. Optionally expand via ``get_impact`` for each changed symbol to
     include downstream call-graph reach.
  3. Match the impacted qualnames and file paths against the content
     of recent memories (pure-logic matcher in core).
  4. Return a deterministic report; the caller decides whether to bump
     heat, tag, or notify.

Read-only by default. If ``apply_heat_bump=True`` and the match set is
small (≤ 20), the handler calls ``update_memory_heat`` for each match
with a capped delta — the same ``_IMPACT_BOOST`` as the preemptive hook.

When AP is disabled the handler returns ``status=skipped`` with the
usual explanation.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.change_impact_matcher import match_memories
from mcp_server.handlers.recall import _get_store  # existing memo root
from mcp_server.infrastructure.ap_bridge import (
    APBridge,
    is_enabled,
    resolve_graph_path,
)
from mcp_server.handlers._tool_meta import READ_ONLY


_IMPACT_BOOST = 0.15  # matches hooks/pipeline_impact_bump.py
_MAX_HEAT_BUMPS = 20
_MAX_MEMORIES_SCANNED = 1000


schema = {
    "title": "Change impact",
    "annotations": READ_ONLY,
    "description": (
        "Report which Cortex memories reference code that changed in a "
        "commit (ADR-0046 Phase 4). Uses automatised-pipeline's "
        "detect_changes and optionally get_impact to compute the "
        "symbol/file impact set, then matches against recent memories. "
        "Read-only by default; pass apply_heat_bump=true to nudge heat "
        "on the top 20 matches by +0.15. Requires AP enabled "
        "(CORTEX_MEMORY_AP_ENABLED=1, the default); returns "
        "status=skipped otherwise."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "base": {"type": "string", "default": "HEAD~1"},
            "head": {"type": "string", "default": "HEAD"},
            "expand_impact": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Expand each changed symbol through ``get_impact`` "
                    "to include downstream dependents."
                ),
            },
            "apply_heat_bump": {
                "type": "boolean",
                "default": False,
                "description": "Write heat bumps to matched memories.",
            },
        },
    },
}


def _extract_symbols_and_files(payload: Any) -> tuple[list[str], list[str]]:
    """Normalize AP's ``detect_changes`` response. AP returns either a
    list of ``{symbol, file, kind}`` rows or a wrapped ``{changes: [...]}``
    object; we tolerate both."""
    rows: list[dict] = []
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        inner = payload.get("changes") or payload.get("rows") or payload.get("content")
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
    symbols, files = [], []
    seen_s, seen_f = set(), set()
    for r in rows:
        q = r.get("qualified_name") or r.get("symbol") or ""
        f = r.get("file_path") or r.get("file") or ""
        if q and q not in seen_s:
            seen_s.add(q)
            symbols.append(str(q))
        if f and f not in seen_f:
            seen_f.add(f)
            files.append(str(f))
    return symbols, files


async def _collect_impact(
    bridge: APBridge,
    graph_path: str,
    base: str,
    head: str,
    *,
    expand: bool,
) -> tuple[list[str], list[str]]:
    payload = await bridge.call(
        "detect_changes",
        {"graph_path": graph_path, "base": base, "head": head},
    )
    symbols, files = _extract_symbols_and_files(payload)
    if not expand or not symbols:
        return symbols, files
    # Expand via get_impact for each direct symbol; dedupe.
    seen = set(symbols)
    for sym in list(symbols):
        resp = await bridge.call(
            "get_impact",
            {"graph_path": graph_path, "symbol_id": sym},
        )
        more_s, _ = _extract_symbols_and_files(resp)
        for q in more_s:
            if q not in seen:
                seen.add(q)
                symbols.append(q)
    return symbols, files


def _apply_heat_bumps(store: Any, matches: list, boost: float) -> int:
    """Bump heat on the first _MAX_HEAT_BUMPS matches. Returns count."""
    bumped = 0
    for m in matches[:_MAX_HEAT_BUMPS]:
        mid = m.memory_id
        try:
            cur = store.get_memory(int(mid)) if str(mid).isdigit() else None
        except Exception:
            cur = None
        if not cur:
            continue
        new_heat = min(1.0, float(cur.get("heat_base") or 0.0) + boost)
        try:
            store.update_memory_heat(int(mid), new_heat)
            bumped += 1
        except Exception:
            pass
    return bumped


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    if not is_enabled():
        return {
            "status": "skipped",
            "reason": "ap_disabled",
            "detail": (
                "AP is disabled. Set CORTEX_MEMORY_AP_ENABLED=1 in your "
                "MCP config (default) and install automatised-pipeline "
                "to compute change impact."
            ),
        }
    gp = resolve_graph_path()
    if not gp:
        return {
            "status": "skipped",
            "reason": "graph_path_unset",
            "detail": (
                "Set CORTEX_AP_GRAPH_PATH to the LadybugDB graph dir "
                "produced by a prior index_codebase call."
            ),
        }
    base = str(args.get("base") or "HEAD~1")
    head = str(args.get("head") or "HEAD")
    expand = bool(args.get("expand_impact", False))
    apply_bump = bool(args.get("apply_heat_bump", False))

    bridge = APBridge()
    symbols, files = await _collect_impact(
        bridge,
        gp,
        base,
        head,
        expand=expand,
    )
    await bridge.close()

    store = _get_store()
    memories = store.get_all_memories_for_validation(limit=_MAX_MEMORIES_SCANNED)
    matches = match_memories(
        impacted_symbols=symbols,
        impacted_files=files,
        memories=memories,
    )
    bumped = _apply_heat_bumps(store, matches, _IMPACT_BOOST) if apply_bump else 0

    return {
        "status": "ok",
        "base": base,
        "head": head,
        "impact": {
            "symbols": symbols,
            "files": files,
            "expanded": expand,
        },
        "matches": [
            {
                "memory_id": m.memory_id,
                "matched_symbols": m.matched_symbols,
                "matched_files": m.matched_files,
                "match_count": m.match_count,
            }
            for m in matches
        ],
        "heat_bumped": bumped,
    }


__all__ = ["handler", "schema"]
