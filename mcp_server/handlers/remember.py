"""Handler: remember — store a memory through the hierarchical predictive coding gate.

Composition root: wires core modules + infrastructure storage + embeddings.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import thermodynamics, write_gate
from mcp_server.core.domain_detector import detect_domain
from mcp_server.core.global_detector import detect_global
from mcp_server.handlers.remember_helpers import (
    apply_modulations,
    evaluate_gate,
    insert_and_post_process,
    try_curation,
)
from mcp_server.handlers.remember_response import build_merge_response
from mcp_server.infrastructure import wiki_store
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": "Store a memory through the predictive coding write gate.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The memory content to store"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags",
            },
            "directory": {
                "type": "string",
                "description": "Directory context (defaults to cwd)",
            },
            "domain": {
                "type": "string",
                "description": "Domain override (auto-detected if omitted)",
            },
            "source": {
                "type": "string",
                "description": "Memory source: session, tool, user, consolidation",
            },
            "force": {
                "type": "boolean",
                "description": "Bypass write gate (always store)",
            },
            "agent_topic": {
                "type": "string",
                "description": "Agent context tag (e.g., 'engineer', 'researcher')",
            },
            "is_global": {
                "type": "boolean",
                "description": "Mark as global memory visible to all projects",
            },
            "created_at": {
                "type": "string",
                "description": "Original timestamp (ISO 8601) for imported memories",
            },
        },
        "required": ["content"],
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _resolve_domain(directory: str, domain: str) -> str:
    from mcp_server.shared.domain_mapping import (
        resolve_cwd,
        resolve_domain as resolve_hint,
    )

    # Shannon: cwd is the minimum sufficient statistic for domain identity.
    # Try git-root resolution first (most reliable), then profile detection fallback.
    if directory:
        resolved = resolve_cwd(directory)
        if resolved:
            return resolved
    if domain:
        return resolve_hint(domain)
    if directory:
        # Fallback to profile-based detection
        profiles = load_profiles()
        detection = detect_domain({"cwd": directory}, profiles)
        detected = detection.get("domain", "") or ""
        return resolve_hint(detected) if detected else ""
    return ""


def _enrich_mod_with_gate(mod: dict, gate: dict) -> None:
    """Copy gate signals into the modulation dict for response building."""
    mod.update(
        {
            "gate_reason": gate["gate_reason"],
            "emb_nov": gate["emb_nov"],
            "ent_nov": gate["ent_nov"],
            "temp_nov": gate["temp_nov"],
            "struct_nov": gate["struct_nov"],
        }
    )


def _parse_args(
    args: dict[str, Any],
) -> tuple[str, list, str, str, bool, str, bool, str | None]:
    """Extract and default handler arguments."""
    return (
        args["content"],
        args.get("tags", []),
        args.get("directory", ""),
        args.get("source", "user"),
        args.get("force", False),
        args.get("agent_topic", ""),
        args.get("is_global", False),
        args.get("created_at"),
    )


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store a memory with thermodynamic properties and predictive coding gate."""
    if not args or not args.get("content"):
        return {"stored": False, "reason": "no_content"}

    content, tags, directory, source, force, agent_topic, is_global, created_at = (
        _parse_args(args)
    )
    store, emb_engine = _get_store(), get_embedding_engine()
    domain = _resolve_domain(directory, args.get("domain", ""))
    embedding = emb_engine.encode(content)
    valence = thermodynamics.compute_valence(content)

    gate = evaluate_gate(content, tags, embedding, force, store, emb_engine)
    if not gate["should_store"]:
        return write_gate.build_rejection_response(
            gate["emb_nov"],
            gate["ent_nov"],
            gate["temp_nov"],
            gate["struct_nov"],
            gate["score"],
            gate["gate_reason"],
            gate["importance"],
        )

    heat = thermodynamics.apply_surprise_boost(
        1.0, gate["score"], get_memory_settings().SURPRISE_BOOST
    )
    mod = apply_modulations(
        content,
        tags,
        heat,
        gate["importance"],
        valence,
        domain,
        gate["ent_names"],
        gate["known"],
        store,
    )
    _enrich_mod_with_gate(mod, gate)

    # Auto-detect global when not explicitly set
    if not is_global:
        is_global, _global_score, global_reason = detect_global(content, tags)
    else:
        global_reason = "explicit"

    action, mid = try_curation(
        content, embedding, force, store, emb_engine, tags, mod["heat"]
    )
    if action == "merge":
        return build_merge_response(mid, domain, mod, gate)

    result = insert_and_post_process(
        content,
        embedding,
        tags,
        source,
        domain,
        directory,
        action,
        mid,
        gate["sims"],
        gate["vec_hits"],
        gate["ent_names"],
        gate["extracted"],
        mod,
        gate["score"],
        store,
        emb_engine,
        agent_context=agent_topic,
        is_global=is_global,
        created_at=created_at,
    )
    if is_global and result.get("stored"):
        result["is_global"] = True
        result["global_reason"] = global_reason

    # Promote decision-shaped memories to the authored wiki layer.
    # Delegated entirely to wiki_store.sync_memory, which never raises.
    if result.get("stored") and result.get("memory_id") is not None:
        wiki_path = wiki_store.sync_memory(
            WIKI_ROOT,
            memory_id=result["memory_id"],
            content=content,
            tags=tags,
            domain=domain,
        )
        if wiki_path:
            result["wiki_page"] = wiki_path

    return result
