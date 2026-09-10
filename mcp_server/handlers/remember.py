"""Handler: remember — store a memory through the flat 4-signal predictive coding gate.

Composition root: wires core modules + infrastructure storage + embeddings.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import capture_origin
from mcp_server.core import (
    thermodynamics,
    write_gate,
)
from mcp_server.shared import write_class as write_class_module
from mcp_server.errors import ValidationError
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.core.domain_detector import detect_domain
from mcp_server.core.global_detector import detect_global
from mcp_server.handlers.remember_helpers import (
    apply_modulations,
    evaluate_gate,
    evaluate_observed_gate,
    observe_gate,
    insert_and_post_process,
    try_block_replica_upsert,
    try_curation,
    update_user_mood_ema,
    validate_supersede_target,
)
from mcp_server.handlers.remember_response import build_merge_response
from mcp_server.handlers.remember_preflight import (
    GateOptions,
    GateRequest,
    bound_rejection,
    prepare_gate,
)
from mcp_server.handlers.remember_schema import schema
from mcp_server.handlers.remember_prepared import PreparedEncoding, PreparedWrite
from mcp_server.handlers import wiki_memory_sync
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import (
    get_memory_settings,
    root_agent_topic,
)
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.shared.domain_mapping import resolve_cwd, resolve_domain as resolve_hint
from mcp_server.shared.content_hardening import harden_content

__all__ = ["schema", "handler"]

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _resolve_domain(directory: str, domain: str) -> str:

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
) -> tuple[str, list, str, str, bool, str, bool, str | None, float | None, str | None]:
    """Extract and default handler arguments.

    source: ADR-0436"""
    raw_initial = args.get("initial_heat")
    initial_heat: float | None = None
    if raw_initial is not None:
        try:
            initial_heat = max(0.0, min(1.0, float(raw_initial)))
        except (TypeError, ValueError):
            initial_heat = None
    return (
        args["content"],
        args.get("tags", []),
        args.get("directory", ""),
        args.get("source", "user"),
        args.get("force", False),
        args.get("agent_topic", ""),
        args.get("is_global", False),
        args.get("created_at"),
        initial_heat,
        args.get("write_class"),
    )


def _harden_args(args: dict[str, Any] | None) -> bool:
    """Preserve ingestion hardening and connection-rooted scope before validation."""
    if not args or not args.get("content"):
        return False
    args["content"] = harden_content(args["content"])
    if not args["content"]:
        return False
    root = root_agent_topic()
    if root is not None:
        args["agent_topic"] = root
    return True


def _validated_write_class(args: dict[str, Any]) -> str:
    """M-D2: explicit invalid classes fail; omitted classes use source fallback."""
    try:
        write_class_module.validate_write_class(args.get("write_class"))
    except ValueError as exc:
        raise ValidationError(
            str(exc), {"tool": "remember", "field": "write_class"}
        ) from exc
    return write_class_module.classify_write_class(
        {"write_class": args.get("write_class"), "source": args.get("source", "user")}
    )


def _resolved_origin(args: dict[str, Any], write_class: str) -> str:
    """trust the producing channel, never attacker-controlled content.

    Only an absent tool name on a deliberate write is promoted to deliberate.
    Named but unknown tools keep UNKNOWN; auto captures cannot claim this bypass.

    source: ADR-0436"""
    origin_tool = str(args.get("origin_tool") or "").strip()
    origin = capture_origin.classify_capture_origin(origin_tool)
    if not origin_tool and write_class == write_class_module.DELIBERATE:
        return capture_origin.ORIGIN_DELIBERATE
    return origin


def _prepare_request(args: dict, store: MemoryStore, write_class: str) -> GateRequest:
    domain = _resolve_domain(args.get("directory", ""), args.get("domain", ""))
    origin = _resolved_origin(args, write_class)
    return GateRequest(
        args["content"],
        args.get("tags", []),
        store,
        GateOptions(args.get("force", False), domain, write_class, origin),
    )


def prepare_write(args: dict[str, Any] | None) -> PreparedWrite | dict:
    """Run the original pre-encode phase in order; never construct the encoder."""
    if not _harden_args(args):
        return {"stored": False, "action": "rejected", "reason": "no_content"}
    assert args is not None  # established by ingestion hardening above
    parsed = _parse_args(args)
    write_class = _validated_write_class(args)
    store = _get_store()
    supersedes_id, rejection = validate_supersede_target(
        args.get("supersedes_id"), store
    )
    if rejection is not None:
        return rejection
    request = _prepare_request(args, store, write_class)
    observed = prepare_gate(request, observe_gate)
    if observed is not None:
        rejection = bound_rejection(request, observed)
        if rejection is not None:
            return rejection
    return PreparedWrite(parsed, request, observed, supersedes_id)


async def _handler_impl(
    args: dict[str, Any] | None = None,
    prepared_encoding: PreparedEncoding | None = None,
) -> dict[str, Any]:
    """Store a memory, optionally continuing an explicitly prepared internal write."""
    if prepared_encoding is not None:
        prepared = prepared_encoding.checked()
    else:
        prepared = prepare_write(args)
    if isinstance(prepared, dict):
        return prepared
    (
        content,
        tags,
        directory,
        source,
        force,
        agent_topic,
        is_global,
        created_at,
        initial_heat,
        _write_class_arg,
    ) = prepared.parsed
    request, observed = prepared.request, prepared.observed
    store, supersedes_id = request.store, prepared.supersedes_id
    domain = request.options.domain
    resolved_write_class, resolved_origin = (
        request.options.write_class,
        request.options.origin,
    )
    if prepared_encoding is None or prepared_encoding.outcome.encoded is None:
        emb_engine = get_embedding_engine()
        embedding = emb_engine.encode(content)
    else:
        emb_engine = prepared_encoding.outcome.engine
        embedding = prepared_encoding.outcome.encoded.value()
    # i7d3/W3-2: stored vectors encode the exact hardened raw content;
    # normalization remains scoped to the novelty gate, evaluated below.
    valence = thermodynamics.compute_valence(content)

    if observed is not None:
        gate = evaluate_observed_gate(request, observed, embedding, emb_engine)
    else:
        gate = evaluate_gate(
            content,
            tags,
            embedding,
            force,
            store,
            emb_engine,
            domain=domain,
            write_class=resolved_write_class,
            origin=resolved_origin,
        )
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

    # Baseline heat defaults to 1.0. Callers may pass an explicit initial_heat
    # to set a different baseline; age-based decay is NOT applied here — it is
    # the read-time job of effective_heat() via the heat_base_set_at anchor
    # (A3 decay clock), keeping a single canonical age-decay path. Surprise
    # boost applies on top.
    baseline_heat = initial_heat if initial_heat is not None else 1.0
    heat = thermodynamics.apply_surprise_boost(
        baseline_heat, gate["score"], get_memory_settings().SURPRISE_BOOST
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

    mid: int | None
    if supersedes_id is not None:
        # source: ADR-0436
        action, mid = "supersede", supersedes_id
    else:
        # source: ADR-0436
        upserted, upsert_id = try_block_replica_upsert(
            content, embedding, tags, source, store
        )
        if upserted and upsert_id is not None:
            return {
                "stored": True,
                "memory_id": upsert_id,
                "action": "stored",
                "reason": "block-replica-refreshed",
            }

        action, mid = try_curation(
            content, embedding, force, store, emb_engine, tags, mod["heat"]
        )
        if action == "merge":
            # Mood signal still updates on merge — the user authored the content,
            # whether we keep it as a new row or fold it into an existing one.
            update_user_mood_ema(content, source, store)
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
        gate["neighbors"],
        gate["ent_names"],
        gate["extracted"],
        mod,
        gate["score"],
        store,
        emb_engine,
        agent_context=agent_topic,
        is_global=is_global,
        created_at=created_at,
        write_class=resolved_write_class,
        origin=resolved_origin,
    )
    if is_global and result.get("stored"):
        result["is_global"] = True
        result["global_reason"] = global_reason

    # MOOD_CONGRUENT_RERANK signal-feed (Bower 1981 mood-congruent recall):
    # EMA-update user_mood.valence from VADER compound on user-authored
    # content. Non-user sources are ignored to keep the signal faithful
    # to the user's affective state. See remember_helpers.update_user_mood_ema
    # for the contract and source-discipline notes.
    if result.get("stored"):
        update_user_mood_ema(content, source, store)

    # source: ADR-0436
    if result.get("stored") and result.get("memory_id") is not None:
        try:
            wiki_path = wiki_memory_sync.sync_memory_strict(
                WIKI_ROOT,
                memory_id=result["memory_id"],
                content=content,
                tags=tags,
                domain=domain,
            )
            if wiki_path:
                result["wiki_page"] = wiki_path
        except Exception as exc:  # noqa: BLE001 — partial-failure boundary — wiki-sync failure is surfaced in result['warnings'] with type+message
            # Partial failure — memory is stored but wiki sync failed.
            # Surfacing the exception type + message preserves the ability
            # to diagnose recurring failures (e.g., disk full, path escape).
            warnings = result.setdefault("warnings", [])
            warnings.append(
                {
                    "scope": "wiki_sync",
                    "memory_id": result["memory_id"],
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    return result


# source: ADR-0436
handler = instrument("remember", _handler_impl, result_count_key=None)
